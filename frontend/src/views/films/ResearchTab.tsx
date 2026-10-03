'use client';

import { useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import Panel from '../../components/terminal/Panel';
import Rows, { cell } from '../../components/terminal/bodies/Rows';
import { panelState } from '../../components/terminal/states';
import { getResearch, type ResearchOptions, type ResearchRow } from '../../services/researchApi';
import { toCsv } from '../../lib/csv';

const CONTROL = 'min-w-0 max-w-full rounded border border-term-rule bg-term-bg px-2 py-2 text-t115 text-term-ink';
const BUTTON = 'rounded border border-term-rule px-3 py-2 text-t11 text-term-accent disabled:opacity-50';
const rating = (value: number | null) => value === null ? '—' : `${value.toFixed(2)}★`;
const signed = (value: number) => `${value > 0 ? '+' : ''}${value}`;

export default function ResearchTab({ profiles, available }: { profiles: string[]; available: string[] }) {
  const params = useSearchParams();
  const [exporting, setExporting] = useState(false);
  const [exportMessage, setExportMessage] = useState('');
  const today = new Date().toISOString().slice(0, 10);
  const requestedPage = Number(params.get('research_page'));
  const page = Number.isSafeInteger(requestedPage) && requestedPage >= 0 && requestedPage <= 1_000_000 ? requestedPage : 0;
  const options: ResearchOptions = {
    from: params.get('research_from') ?? `${today.slice(0, 4)}-01-01`,
    to: params.get('research_to') ?? today,
    basis: params.get('research_basis') ?? 'watched',
    dimension: params.get('research_dimension') ?? 'genre',
    trait: params.get('research_trait') ?? '', q: params.get('research_q') ?? '',
    sort: params.get('research_sort') ?? 'newest',
    compareProfiles: params.getAll('compare_profiles'), offset: page * 50, limit: 50,
  };
  const query = useQuery({
    queryKey: ['research', profiles, options], queryFn: () => getResearch(profiles, options),
    enabled: profiles.length > 0, staleTime: 60_000,
  });
  const data = query.data;
  function update(values: Record<string, string | string[] | null>) {
    const next = new URLSearchParams(window.location.search);
    next.delete('research_page');
    Object.entries(values).forEach(([key, value]) => {
      next.delete(key);
      if (Array.isArray(value)) value.forEach((item) => next.append(key, item));
      else if (value) next.set(key, value);
    });
    window.history.pushState(null, '', `/films?${next}`);
  }
  async function exportEvidence() {
    if (!data) return;
    setExporting(true);
    setExportMessage('Preparing every matching row…');
    try {
      const rows: ResearchRow[] = [];
      const seen = new Set<number>();
      const expected = data.evidence.total;
      for (let offset = 0; offset < expected; offset += 10000) {
        const batch = await getResearch(profiles, { ...options, offset, limit: 10000 });
        if (batch.evidence.total !== expected || !batch.evidence.rows.length) throw new Error('The data changed during export. Refresh the view and try again.');
        for (const row of batch.evidence.rows) {
          if (seen.has(row.event_id)) throw new Error('The data changed during export. Refresh the view and try again.');
          seen.add(row.event_id);
          rows.push(row);
        }
      }
      if (rows.length !== expected) throw new Error('The export is incomplete. Please refresh and try again.');
      const csv = toCsv(['event_id', 'movie_id', 'title', 'year', 'profile', 'groups', 'analysis_date', 'watched_date', 'logged_date', 'rating_0_5_to_5', 'rewatch', 'source_kind'], rows.map((row) => [row.event_id, row.movie_id, row.title, row.year, row.username, row.groups.join(' / '), row.date, row.watched_date, row.logged_date, row.rating, row.rewatch, row.source_kind]));
      const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8;' }));
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `spyboxd-watches-${options.from}-${options.to}.csv`;
      anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setExportMessage(`Exported ${rows.length} matching watch events. The CSV uses the current filters and date basis.`);
    } catch (error) {
      setExportMessage(error instanceof Error ? error.message : 'Export failed. Please try again.');
    } finally {
      setExporting(false);
    }
  }
  const pending = panelState({ isLoading: query.isLoading, error: query.error, isEmpty: !data, onRetry: () => query.refetch(), empty: { title: 'Choose a profile or group', body: 'Select at least one imported profile above to start a research view.' } });
  return <>
    <div className="col-span-full font-term-sans">
      <form key={params.toString()} className="flex flex-wrap items-end gap-3" onSubmit={(event) => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        const values = Object.fromEntries(['from', 'to', 'basis', 'dimension', 'q', 'sort'].map((key) => [`research_${key}`, String(form.get(key) ?? '')]));
        update({ ...values, research_trait: values.research_dimension !== options.dimension ? null : options.trait });
      }}>
        <label className="grid gap-1 text-t11">From<input className={CONTROL} aria-label="Research from" type="date" name="from" min="1900-01-01" max={today} defaultValue={options.from} required /></label>
        <label className="grid gap-1 text-t11">Through (UTC today or earlier)<input className={CONTROL} aria-label="Research through" type="date" name="to" min="1900-01-01" max={today} defaultValue={options.to} required /></label>
        <label className="grid gap-1 text-t11">Date basis<select className={CONTROL} name="basis" aria-label="Research date basis" defaultValue={options.basis}><option value="watched">Watch date</option><option value="logged">Log date, watch-date fallback</option></select></label>
        <label className="grid gap-1 text-t11">Break down by<select className={CONTROL} name="dimension" aria-label="Research dimension" defaultValue={options.dimension}>{['genre', 'director', 'language', 'country', 'decade'].map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
        <label className="grid gap-1 text-t11">Find film or profile<input className={CONTROL} name="q" aria-label="Search research evidence" type="search" maxLength={200} defaultValue={options.q} /></label>
        <label className="grid gap-1 text-t11">Order evidence<select className={CONTROL} name="sort" aria-label="Order research evidence" defaultValue={options.sort}><option value="newest">Newest first</option><option value="oldest">Oldest first</option><option value="title">Film title</option><option value="rating">Highest rating</option></select></label>
        <button className={BUTTON} type="submit">Apply research filters</button>
      </form>
      <details className="mt-3 border-y border-term-rule py-3">
        <summary className="cursor-pointer text-t115 text-term-accent">Compare a second group · {options.compareProfiles.length} selected</summary>
        <p className="text-t11 text-term-muted">Group A is the profile selection above. Group B uses the same dates and filters; shared members are labelled, not treated as independent evidence.</p>
        <div className="flex flex-wrap gap-3">{available.map((name) => <label key={name} className="flex items-center gap-1 text-t11"><input type="checkbox" aria-label={`Compare @${name}`} checked={options.compareProfiles.includes(name)} onChange={(event) => update({ compare_profiles: event.target.checked ? [...options.compareProfiles, name] : options.compareProfiles.filter((value) => value !== name) })} />@{name}</label>)}</div>
        <button className={`${BUTTON} mt-3`} type="button" onClick={() => update({ compare_profiles: [] })}>Clear comparison group</button>
      </details>
      {options.trait ? <p className="text-t115">Filtering all summaries and evidence to {options.dimension}: <strong>{options.trait}</strong>. <button className={BUTTON} onClick={() => update({ research_trait: null })}>Clear trait filter</button></p> : null}
    </div>
    <Panel title="COMPARE PERIODS AND GROUPS" src="active watch_events · identical filters" wide blurb="Compare equal-length periods, then check a second group without confusing group size with watching intensity." caveat={data?.method}>
      {pending ?? <div className="grid grid-cols-1 gap-4 p-3 md:grid-cols-2">{data?.groups.map((group) => <div key={group.label} className="min-w-0">
        <h3 className="m-0 font-term-sans text-t13">Group {group.label} · {group.profiles.length} members</h3>
        <p className="break-words font-term-sans text-t11 text-term-muted">{group.profiles.map((name) => `@${name}`).join(', ')}</p>
        <p className="font-term-sans text-t11">{data.period.from}–{data.period.to} vs {data.period.previous_from}–{data.period.previous_to} ({data.period.days} days each)</p>
        <Rows columns="minmax(0,1fr) 78px 78px" head={['MEASURE', 'CURRENT', 'PREVIOUS']} rows={[
          { cells: [cell('Recorded watches', { wrap: true }), cell(group.current.watches), cell(group.previous.watches)] },
          { cells: [cell('Unique films', { wrap: true }), cell(group.current.films), cell(group.previous.films)] },
          { cells: [cell('Rated events / average', { wrap: true }), cell(`${group.current.rated} / ${rating(group.current.average_rating)}`, { wrap: true }), cell(`${group.previous.rated} / ${rating(group.previous.average_rating)}`, { wrap: true })] },
          { cells: [cell('Watches / member / 30d', { wrap: true }), cell(group.current.watches_per_member_30_days.toFixed(2)), cell(group.previous.watches_per_member_30_days.toFixed(2))] },
          { cells: [cell('Rewatches'), cell(group.current.rewatches), cell(group.previous.rewatches)] },
        ]} />
        <p className="font-term-sans text-t11">Watch change: {signed(group.change.watches)} · {group.change.watches_percent === null ? 'No previous watches to calculate a percentage' : `${signed(group.change.watches_percent)}%`}. {group.current.active_members} of {group.current.members} members have recorded activity.</p>
      </div>)}</div>}
      {data?.coverage.warnings.length ? <details className="m-3 font-term-sans text-t11" open><summary className="text-term-accent">Coverage and interpretation limits</summary><ul>{data.coverage.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></details> : null}
    </Panel>
    <Panel title="INDIVIDUAL CONTRIBUTIONS" src="same filtered diary events" blurb="Who contributes to each group total? A missing rating is not a zero-star opinion.">
      {pending ?? <Rows columns="45px minmax(110px,1fr) 65px 100px" head={['GROUP', 'PROFILE', 'WATCHES', 'RATED / AVG']} rows={data?.groups.flatMap((group) => group.per_profile.map((person) => ({ cells: [cell(group.label), cell(`@${person.username}`, { wrap: true }), cell(person.watches), cell(`${person.rated} / ${rating(person.average_rating)}`, { wrap: true })] }))) ?? []} />}
    </Panel>
    <Panel title="WHAT DRIVES THIS TREND" src="dated events × film metadata" blurb="Select a trait to inspect its exact films and apply it to both periods and groups." caveat="Up to 50 traits per group. Samples are watch events, not unique films. Films can have multiple traits, so counts overlap. Unmatched metadata is not assigned a made-up category.">
      {pending ?? <div className="space-y-3 p-3">{data?.groups.map((group) => <div key={group.label}><h3 className="font-term-sans text-t115">Group {group.label}</h3>{group.traits.length ? <div className="flex flex-wrap gap-2">{group.traits.map((item) => <button key={item.label} className={BUTTON} aria-label={`Inspect ${item.label} in group ${group.label}`} onClick={() => update({ research_trait: item.label })}>{item.label} · {item.watches} watches · {item.rated} rated · {rating(item.average_rating)}</button>)}</div> : <p className="font-term-sans text-t11 text-term-muted">No matching trait evidence.</p>}</div>)}</div>}
    </Panel>
    <Panel title="THE EXACT WATCHES BEHIND THE NUMBERS" src="one row per active watch event" wide blurb="Filter or sort above, follow a film to its public page, or export every matching row—not just this page." caveat="A shared member's event appears once, labelled A / B. Source kind identifies the import surface. Dates and ratings are recorded observations, not proof people watched together.">
      <div className="flex flex-wrap items-center gap-3 p-3 font-term-sans text-t11"><button className={BUTTON} disabled={!data || exporting || !data.evidence.total} onClick={exportEvidence}>{exporting ? 'Preparing export…' : `Export all ${data?.evidence.total ?? 0} matching watches (CSV)`}</button><span role="status">{exportMessage}</span></div>
      {pending ?? (data?.evidence.total ? <>
        <Rows columns="90px 45px minmax(170px,2fr) minmax(120px,1fr) 58px 65px 110px" head={['DATE', 'GROUP', 'FILM', 'PROFILE', 'RATING', 'REWATCH', 'SOURCE']} rows={data.evidence.rows.map((row) => ({ cells: [cell(row.date), cell(row.groups.join('/')), cell(row.film_url?.startsWith('https://letterboxd.com/') ? <a className="text-term-accent" href={row.film_url} target="_blank" rel="noreferrer">{row.title} ({row.year ?? '—'})</a> : `${row.title} (${row.year ?? '—'})`, { wrap: true }), cell(`@${row.username}`, { wrap: true }), cell(rating(row.rating)), cell(row.rewatch ? 'Yes' : 'No'), cell(row.source_kind, { wrap: true })] }))} />
        <div className="flex flex-wrap items-center gap-3 p-3 font-term-sans text-t11"><button className={BUTTON} disabled={!page} onClick={() => update({ research_page: String(page - 1) })}>Previous evidence page</button><span>{Math.min(page * 50 + 1, data.evidence.total)}–{Math.min((page + 1) * 50, data.evidence.total)} of {data.evidence.total} events</span><button className={BUTTON} disabled={(page + 1) * 50 >= data.evidence.total} onClick={() => update({ research_page: String(page + 1) })}>Next evidence page</button></div>
      </> : <p className="p-3 font-term-sans text-t115">No diary events match these filters. Try a wider date range or clear the title/trait filter; this does not prove the profiles were inactive.</p>)}
    </Panel>
  </>;
}
