'use client';

import React from 'react';
import { motion } from 'framer-motion';
import { useQuery } from '@tanstack/react-query';
import { BarChart3, Trophy } from 'lucide-react';

import { profileStatsApi } from '../../services/api';
import type {
  ProfileStatsBucket,
  ProfileStatsCountryBucket,
  ProfileStatsPerson,
} from '../../services/api';

/** Below this, the metadata gap is worth saying once at the panel level. */
const ENRICHMENT_CAVEAT_THRESHOLD = 0.95;

function formatCount(value: number): string {
  return value.toLocaleString();
}

function formatHours(value: number): string {
  return value >= 10 ? Math.round(value).toLocaleString() : value.toFixed(1);
}

/**
 * Floors rather than rounds: a partial figure must never present itself as a
 * confident "100%" just because it is close.
 */
function formatRatio(ratio: number): string {
  const bounded = Math.max(0, Math.min(1, ratio));
  return `${Math.floor(bounded * 100)}%`;
}

function normalizeKey(key: string): string {
  return key
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');
}

/**
 * Letterboxd's stats page labels its figures differently per account tier, so
 * each of our headline stats accepts a few plausible key spellings. Anything
 * that does not match is simply not compared — the profile header already
 * renders the raw snapshot in full.
 */
const REPORTED_KEY_ALIASES: Record<string, string[]> = {
  films: ['films', 'films_watched', 'total_films', 'watched'],
  hours: ['hours', 'hours_watched', 'total_hours'],
  directors: ['directors', 'distinct_directors', 'unique_directors'],
  countries: ['countries', 'distinct_countries', 'unique_countries'],
  longest_streak: ['longest_streak', 'longest_streak_weeks', 'longest_streak_of_weeks'],
  multi_film_days: ['multi_film_days', '2_film_days', 'two_film_days'],
};

function buildReportedIndex(
  reported: Record<string, number | string | null> | null | undefined,
): Map<string, string> {
  const index = new Map<string, string>();
  for (const [key, value] of Object.entries(reported ?? {})) {
    if (value === null || value === undefined || value === '') continue;
    index.set(
      normalizeKey(key),
      typeof value === 'number' ? formatCount(value) : String(value),
    );
  }
  return index;
}

/**
 * Letterboxd's own figure for one of our stats, phrased as a comparison. When
 * the two agree we say so instead of printing the same number twice.
 */
function reportedNote(
  index: Map<string, string>,
  statKey: string,
  ourValue: string,
): string | null {
  for (const alias of REPORTED_KEY_ALIASES[statKey] ?? []) {
    const value = index.get(alias);
    if (value === undefined) continue;
    return value === ourValue ? 'matches Letterboxd' : `Letterboxd: ${value}`;
  }
  return null;
}

type HeadlineStat = {
  key: string;
  label: string;
  value: string;
  hint?: string;
};

type BarRow = {
  id: string;
  label: string;
  title: string;
  count: number;
  averageRating: number | null;
};

function toBarRows(buckets: ProfileStatsBucket[]): BarRow[] {
  return buckets.map((bucket) => ({
    id: bucket.label,
    label: bucket.label,
    title: bucket.label,
    count: bucket.count,
    averageRating: bucket.average_rating,
  }));
}

function toCountryRows(buckets: ProfileStatsCountryBucket[]): BarRow[] {
  return buckets.map((bucket) => ({
    id: bucket.code ?? bucket.label,
    label: bucket.label,
    title: bucket.code ? `${bucket.label} (${bucket.code})` : bucket.label,
    count: bucket.count,
    averageRating: bucket.average_rating,
  }));
}

function AverageRating({ value }: { value: number | null }) {
  return (
    <span
      className="w-8 shrink-0 text-right text-[11px] tabular-nums text-white/35"
      title={value === null ? undefined : `Average rating ${value.toFixed(1)}`}
    >
      {value === null ? '' : value.toFixed(1)}
    </span>
  );
}

function RankedList({
  title,
  subtitle,
  people,
}: {
  title: string;
  subtitle: string | null;
  people: ProfileStatsPerson[];
}) {
  if (people.length === 0) return null;

  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-wide text-white/45">{title}</p>
      {subtitle ? <p className="mt-0.5 text-[11px] text-white/30">{subtitle}</p> : null}
      <ol className="mt-2 space-y-1.5">
        {people.map((person, index) => (
          <li key={person.name} className="flex items-center gap-2 text-sm">
            <span className="w-4 shrink-0 text-right text-[11px] tabular-nums text-white/25">
              {index + 1}
            </span>
            <span className="min-w-0 flex-1 truncate text-white/80" title={person.name}>
              {person.name}
            </span>
            <span className="w-8 shrink-0 text-right text-xs tabular-nums text-white/45">
              {formatCount(person.count)}
            </span>
            <AverageRating value={person.average_rating} />
          </li>
        ))}
      </ol>
    </div>
  );
}

function BreakdownBars({
  title,
  subtitle,
  rows,
}: {
  title: string;
  subtitle: string | null;
  rows: BarRow[];
}) {
  if (rows.length === 0) return null;

  const largest = rows.reduce((max, row) => Math.max(max, row.count), 0);

  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-wide text-white/45">{title}</p>
      {subtitle ? <p className="mt-0.5 text-[11px] text-white/30">{subtitle}</p> : null}
      <ul className="mt-2 space-y-1.5">
        {rows.map((row) => (
          <li key={row.id} className="flex items-center gap-2 text-sm">
            <span className="min-w-0 flex-1 truncate text-white/80" title={row.title}>
              {row.label}
            </span>
            <span className="h-1.5 w-14 shrink-0 overflow-hidden rounded-full bg-white/10">
              <span
                className="block h-full rounded-full bg-cinema-500"
                style={{ width: `${largest > 0 ? Math.max(4, Math.round((row.count / largest) * 100)) : 4}%` }}
              />
            </span>
            <span className="w-8 shrink-0 text-right text-xs tabular-nums text-white/45">
              {formatCount(row.count)}
            </span>
            <AverageRating value={row.averageRating} />
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * The numbers Letterboxd puts behind its Patron-only stats page, computed for
 * every tracked member from their synced history. The endpoint is optional
 * from the page's point of view: any failure, and the panel simply is not
 * there, the same way the follow network bows out.
 */
const ProfileStatsPanel: React.FC<{ username: string; delay?: number }> = ({
  username,
  delay = 0,
}) => {
  const statsQuery = useQuery({
    queryKey: ['profile-stats', username],
    queryFn: () => profileStatsApi.getStats(username),
    enabled: Boolean(username),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  const stats = statsQuery.data;

  // No hooks below this line: the panel disappears entirely when the endpoint
  // is unavailable or has nothing worth showing.
  if (statsQuery.isError || !stats) return null;

  const { coverage, totals, highest_rated: highestRated } = stats;
  if (totals.films === 0 && coverage.films_total === 0) return null;

  const reportedIndex = buildReportedIndex(stats.letterboxd_reported);

  const filmsValue = formatCount(totals.films);
  const hoursValue = totals.hours_watched === null ? null : formatHours(totals.hours_watched);
  const directorsValue = totals.distinct_directors === null
    ? null
    : formatCount(totals.distinct_directors);
  const countriesValue = totals.distinct_countries === null
    ? null
    : formatCount(totals.distinct_countries);
  const streakValue = totals.longest_streak_weeks === null
    ? null
    : formatCount(totals.longest_streak_weeks);
  const multiFilmDaysValue = totals.multi_film_days === null
    ? null
    : formatCount(totals.multi_film_days);

  const headlineCandidates: Array<HeadlineStat | null> = [
    { key: 'films', label: 'Films', value: filmsValue },
    hoursValue !== null
      ? {
          key: 'hours',
          label: 'Hours watched',
          value: hoursValue,
          // Never let a partial runtime sum read as a complete one.
          hint: totals.runtime_coverage < 1
            ? `from ${formatRatio(totals.runtime_coverage)} of films with runtime data`
            : undefined,
        }
      : null,
    directorsValue !== null ? { key: 'directors', label: 'Directors', value: directorsValue } : null,
    countriesValue !== null ? { key: 'countries', label: 'Countries', value: countriesValue } : null,
    streakValue !== null
      ? {
          key: 'longest_streak',
          label: 'Longest streak',
          value: streakValue,
          hint: 'consecutive weeks',
        }
      : null,
    multiFilmDaysValue !== null
      ? {
          key: 'multi_film_days',
          label: 'Multi-film days',
          value: multiFilmDaysValue,
          hint: 'days with 2+ entries',
        }
      : null,
  ];
  const headline = headlineCandidates.filter((stat): stat is HeadlineStat => stat !== null);

  const footnotes = [
    coverage.rated_films > 0 ? `${formatCount(coverage.rated_films)} rated` : null,
    totals.average_rating !== null ? `${totals.average_rating.toFixed(2)} average rating` : null,
    totals.rewatches > 0 ? `${formatCount(totals.rewatches)} rewatches` : null,
    coverage.dated_events > 0 ? `${formatCount(coverage.dated_events)} dated entries` : null,
  ].filter((item): item is string => item !== null);

  const genreRows = toBarRows(stats.genres ?? []);
  const countryRows = toCountryRows(stats.countries ?? []);
  const languageRows = toBarRows(stats.languages ?? []);
  const decadeRows = toBarRows(stats.decades ?? []);

  const topDirectors = stats.top_directors ?? [];
  const topActors = stats.top_actors ?? [];
  const topStudios = stats.top_studios ?? [];
  const hasPeople = topDirectors.length > 0 || topActors.length > 0 || topStudios.length > 0;
  const hasBreakdowns = genreRows.length > 0
    || countryRows.length > 0
    || languageRows.length > 0
    || decadeRows.length > 0;

  const highlightCandidates: Array<{ label: string; name: string; count: number; average: number } | null> = [
    highestRated?.genre
      ? {
          label: 'Highest-rated genre',
          name: highestRated.genre.label,
          count: highestRated.genre.count,
          average: highestRated.genre.average_rating,
        }
      : null,
    highestRated?.decade
      ? {
          label: 'Highest-rated decade',
          name: highestRated.decade.label,
          count: highestRated.decade.count,
          average: highestRated.decade.average_rating,
        }
      : null,
    highestRated?.director
      ? {
          label: 'Highest-rated director',
          name: highestRated.director.name,
          count: highestRated.director.count,
          average: highestRated.director.average_rating,
        }
      : null,
  ];
  const highlights = highlightCandidates.filter(
    (item): item is { label: string; name: string; count: number; average: number } => item !== null,
  );

  // One caveat for the whole panel rather than a footnote on every row.
  const enrichmentCaveat = coverage.films_total > 0
    && coverage.enrichment_ratio < ENRICHMENT_CAVEAT_THRESHOLD
    ? `Film metadata is in for ${formatRatio(coverage.enrichment_ratio)} of ${formatCount(coverage.films_total)} synced films (${formatCount(coverage.films_enriched)}), so the credits, country, language and runtime figures below are drawn from that subset.`
    : null;

  return (
    <motion.section
      className="analysis-panel"
      aria-labelledby="profile-stats-title"
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay }}
    >
      <div className="flex items-center gap-2">
        <BarChart3 className="h-5 w-5 text-cinema-400" aria-hidden="true" />
        <h2 id="profile-stats-title" className="text-xl font-semibold text-white">
          Profile stats
        </h2>
      </div>
      <p className="mt-1 text-sm text-white/60">
        The figures Letterboxd keeps behind Patron, computed here from @{username}
        &rsquo;s synced history.
      </p>

      {enrichmentCaveat ? (
        <p className="mt-3 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs leading-5 text-white/45">
          {enrichmentCaveat}
        </p>
      ) : null}

      <dl className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {headline.map((stat) => {
          const comparison = reportedNote(reportedIndex, stat.key, stat.value);
          return (
            <div
              key={stat.key}
              className="rounded-xl border border-white/10 bg-white/5 px-3 py-2.5 text-center"
            >
              <dt className="text-[10px] font-semibold uppercase tracking-wide text-white/45">
                {stat.label}
              </dt>
              <dd className="mt-1 text-lg font-bold text-white">{stat.value}</dd>
              {stat.hint ? <p className="mt-0.5 text-[10px] leading-4 text-white/35">{stat.hint}</p> : null}
              {comparison ? (
                <p className="mt-0.5 text-[10px] leading-4 text-white/25">{comparison}</p>
              ) : null}
            </div>
          );
        })}
      </dl>

      {footnotes.length > 0 ? (
        <p className="mt-3 text-xs text-white/35">{footnotes.join(' · ')}</p>
      ) : null}

      {hasPeople ? (
        <div className="mt-6 grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
          <RankedList
            title="Top directors"
            subtitle={totals.distinct_directors ? `of ${formatCount(totals.distinct_directors)} seen` : null}
            people={topDirectors}
          />
          <RankedList
            title="Top actors"
            subtitle={totals.distinct_actors ? `of ${formatCount(totals.distinct_actors)} seen` : null}
            people={topActors}
          />
          <RankedList
            title="Top studios"
            subtitle={totals.distinct_studios ? `of ${formatCount(totals.distinct_studios)} seen` : null}
            people={topStudios}
          />
        </div>
      ) : null}

      {hasBreakdowns ? (
        <div className="mt-6 grid gap-5 sm:grid-cols-2 xl:grid-cols-4">
          <BreakdownBars title="Genres" subtitle={null} rows={genreRows} />
          <BreakdownBars
            title="Countries"
            subtitle={totals.distinct_countries ? `of ${formatCount(totals.distinct_countries)} seen` : null}
            rows={countryRows}
          />
          <BreakdownBars
            title="Languages"
            subtitle={totals.distinct_languages ? `of ${formatCount(totals.distinct_languages)} heard` : null}
            rows={languageRows}
          />
          <BreakdownBars title="Decades" subtitle={null} rows={decadeRows} />
        </div>
      ) : null}

      {highlights.length > 0 ? (
        <div className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {highlights.map((highlight) => (
            <div
              key={highlight.label}
              className="rounded-xl border border-cinema-400/20 bg-cinema-500/10 px-3 py-2.5"
            >
              <p className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-cinema-200">
                <Trophy className="h-3 w-3" aria-hidden="true" />
                {highlight.label}
              </p>
              <p className="mt-1 truncate text-sm font-semibold text-white" title={highlight.name}>
                {highlight.name}
              </p>
              <p className="mt-0.5 text-[11px] text-white/40">
                {highlight.average.toFixed(2)} average across {formatCount(highlight.count)} films
              </p>
            </div>
          ))}
        </div>
      ) : null}

      {reportedIndex.size > 0 ? (
        <p className="mt-5 text-[11px] leading-5 text-white/30">
          Muted figures are Letterboxd&rsquo;s own published numbers, shown for comparison. They
          count a member&rsquo;s whole history; ours count what has been synced here.
        </p>
      ) : null}
    </motion.section>
  );
};

export default ProfileStatsPanel;
