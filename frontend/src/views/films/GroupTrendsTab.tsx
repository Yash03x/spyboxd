'use client';

import { useQuery } from '@tanstack/react-query';
import { useSearchParams } from 'next/navigation';
import Panel from '../../components/terminal/Panel';
import Rows, { cell } from '../../components/terminal/bodies/Rows';
import { panelState } from '../../components/terminal/states';
import { insightsApi, type TasteDimension } from '../../services/api';

const DIMENSIONS: TasteDimension[] = ['genre', 'director', 'language', 'country', 'decade'];
const TRAIT_LIMIT = 50;
const languageNames = new Intl.DisplayNames(['en'], { type: 'language' });
const countryNames = new Intl.DisplayNames(['en'], { type: 'region' });

function traitLabel(label: string, dimension: TasteDimension): string {
  if (dimension === 'language' && /^[a-z]{2,3}$/i.test(label)) {
    const name = languageNames.of(label.toLowerCase());
    return name && name.toLowerCase() !== label.toLowerCase() ? `${name} (${label})` : label;
  }
  if (dimension === 'country' && /^[a-z]{2}$/i.test(label)) {
    const name = countryNames.of(label.toUpperCase());
    return name ? `${name} (${label})` : label;
  }
  return label;
}

export default function GroupTrendsTab({ profiles }: { profiles: string[] }) {
  const params = useSearchParams();
  const sort = params.get('trait_order') === 'alignment' ? 'alignment' : 'watched';
  const showAll = params.get('trait_rows') === 'all';
  const timeline = useQuery({
    queryKey: ['taste-timeline', profiles],
    queryFn: () => insightsApi.getTasteTimeline(profiles),
    enabled: profiles.length > 0,
    staleTime: 300_000,
  });
  const taste = useQuery({
    queryKey: ['group-taste-trends', profiles, sort],
    queryFn: () => insightsApi.getTasteDna(profiles, { dimensions: DIMENSIONS, limit: TRAIT_LIMIT, sort }),
    enabled: profiles.length > 0,
    staleTime: 300_000,
  });
  const yearly = timeline.data?.yearly ?? [];
  const requestedYear = Number(params.get('trend_year'));
  const selectedYear = yearly.find((point) => point.year === requestedYear) ?? [...yearly].sort((a, b) => b.year - a.year)[0];
  const dimension = DIMENSIONS.find((value) => value === params.get('trait')) ?? 'genre';
  const traits = taste.data?.dimensions[dimension] ?? [];
  const shownTraits = showAll ? traits : traits.slice(0, 12);
  const update = (key: string, value: string) => {
    // Native history updates the URL-backed client view without a route fetch.
    const next = new URLSearchParams(window.location.search);
    next.set(key, value);
    window.history.pushState(null, '', `/films?${next}`);
  };
  const dateBasis = timeline.data?.summary.date_basis === 'logged' ? 'Recorded log dates' : timeline.data?.summary.date_basis === 'mixed' ? 'Mixed log and watch dates' : 'Recorded watch dates';
  const currentYear = new Date().getFullYear();

  return <>
    <Panel title="THE GROUP OVER TIME" src="watch_events · dated observations" wide
      blurb="Compare the selected group's watching volume, rating habits and rewatches year by year. A watch is one person's diary entry; the same film watched by two people is two watches."
      caveat={`${dateBasis}. ${timeline.data?.summary.undated_known_watches ?? 0} known watches have no usable date and cannot appear here. Years without recorded entries are omitted, not proven inactive. Up to the latest 30 recorded years are shown; a current year is incomplete. ${timeline.data?.coverage.blockers.join(' ') ?? ''}`}>
      <p className="m-0 px-[10px] py-2 font-term-sans text-t105 text-term-muted sm:hidden">Swipe a wide table sideways to see every column.</p>
      {panelState({ isLoading: timeline.isLoading, error: timeline.error, isEmpty: !yearly.length, onRetry: () => timeline.refetch(), empty: { title: 'No dated history for this selection', body: 'Select profiles with imported diary dates to explore trends.' } }) ?? <Rows columns="72px repeat(4,minmax(62px,1fr))" head={['YEAR', 'WATCHES', 'FILMS', 'RATED / AVG', 'REWATCHES']} rows={yearly.map((point) => ({ cells: [
        cell(`${point.year}${point.year === currentYear ? ' YTD' : ''}`), cell(point.watch_events.toLocaleString()), cell(point.unique_films.toLocaleString()), cell(`${point.rated_events} / ${point.average_rating === null ? '—' : `${point.average_rating.toFixed(2)}★`}`, { wrap: true }), cell(point.rewatch_count.toLocaleString()),
      ] }))} />}
    </Panel>
    <Panel title="WHO CONTRIBUTES TO THE GROUP TREND" src="same dated events · per profile"
      blurb="Inspect individual contributions before reading a group total as a shared habit. Ratings average only the rated events, not every watch."
      caveat={`${dateBasis}; each row uses the same selected year. Missing dates or late imports can change the apparent pattern.`}>
      <label className="flex flex-wrap items-center gap-2 px-[10px] py-3 font-term-sans text-t11 text-term-ink3">Year to inspect
        <select aria-label="Year to inspect" disabled={!yearly.length} value={selectedYear?.year ?? ''} onChange={(event) => update('trend_year', event.target.value)} className="rounded border border-term-rule bg-term-bg px-2 py-2 text-t115 text-term-ink disabled:opacity-60">
          {!yearly.length ? <option value="">No recorded years</option> : null}
          {yearly.map((point) => <option key={point.year} value={point.year}>{point.year}{point.year === currentYear ? ' (year to date)' : ''}</option>)}
        </select>
      </label>
      {panelState({ isLoading: timeline.isLoading, error: timeline.error, isEmpty: !selectedYear, onRetry: () => timeline.refetch(), empty: { title: 'No period to compare', body: 'Imported diary dates are needed for a year-by-year comparison.' } }) ?? <Rows columns="minmax(0,1fr) 62px 70px 72px" head={['PROFILE', 'WATCHES', 'RATED', 'AVG']} rows={(selectedYear?.per_profile ?? []).map((point) => ({ cells: [cell(`@${point.username}`, { wrap: true }), cell(String(point.watch_events)), cell(String(point.rated_events)), cell(point.average_rating === null ? '—' : `${point.average_rating.toFixed(2)}★`)] }))} />}
    </Panel>
    <Panel title="THE GROUP'S TASTE, WITH SAMPLE SIZES" src="profile_films × movie_enrichments"
      blurb="Explore genres, directors, languages, countries and decades across the whole selected library. This all-history view is independent of the year selector above."
      caveat={`Up to ${TRAIT_LIMIT} traits per dimension, ordered by ${sort === 'watched' ? 'most watched profile-film pairs' : 'taste alignment, not viewing volume'}. Sample counts profile-film pairs, not unique films. Rated is the sample behind the average; prolific raters have more weight in that average. A film can have several traits, so rows overlap. ${[...(taste.data?.coverage.blockers ?? []), ...(taste.data?.coverage.warnings ?? [])].join(' ')}`}>
      <div className="flex flex-wrap gap-3 px-[10px] py-3 font-term-sans text-t11 text-term-ink3">
        <label className="flex flex-wrap items-center gap-2">Taste dimension
          <select aria-label="Taste dimension" value={dimension} onChange={(event) => update('trait', event.target.value)} className="rounded border border-term-rule bg-term-bg px-2 py-2 text-t115 text-term-ink">
            {DIMENSIONS.map((value) => <option key={value} value={value}>{value[0].toUpperCase() + value.slice(1)}</option>)}
          </select>
        </label>
        <label className="flex flex-wrap items-center gap-2">Order traits
          <select aria-label="Order traits" value={sort} onChange={(event) => update('trait_order', event.target.value)} className="rounded border border-term-rule bg-term-bg px-2 py-2 text-t115 text-term-ink">
            <option value="watched">Most watched</option>
            <option value="alignment">Taste alignment</option>
          </select>
        </label>
      </div>
      {panelState({
        isLoading: taste.isLoading,
        error: taste.error,
        isEmpty: !traits.length,
        onRetry: () => taste.refetch(),
        empty: { title: 'No metadata for this dimension', body: 'The selected films need matching metadata before this can be measured.' },
      }) ?? <>
        <Rows
          columns="minmax(140px,1.4fr) 94px 60px minmax(180px,1fr)"
          head={['TRAIT', 'SAMPLE / RATED', 'AVG', 'WHO WATCHED']}
          rows={shownTraits.map((trait) => ({ cells: [
            cell(traitLabel(trait.label, dimension), { wrap: true }),
            cell(`${trait.sample_size} / ${trait.per_profile.reduce((sum, person) => sum + person.rated_sample_size, 0)}`),
            cell(trait.average_rating === null ? '—' : `${trait.average_rating.toFixed(2)}★`),
            cell(trait.per_profile.filter((person) => person.sample_size > 0)
              .map((person) => `@${person.username} (${person.sample_size})`).join(', '), { wrap: true, size: '10px' }),
          ] }))}
        />
        {traits.length > 12 ? <button
          type="button"
          onClick={() => update('trait_rows', showAll ? '12' : 'all')}
          className="m-2 rounded border border-term-rule px-3 py-2 font-term-sans text-t11 text-term-accent disabled:opacity-60"
        >{showAll ? 'Show the first 12 traits' : `Show all ${traits.length} returned traits`}</button> : null}
      </>}
    </Panel>
  </>;
}
