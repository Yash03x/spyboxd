'use client';

import React from 'react';
import { motion } from 'framer-motion';
import { useQuery } from '@tanstack/react-query';
import { BarChart3, Trophy } from 'lucide-react';

import { profileStatsApi } from '../../services/api';
import type {
  ProfileStatsBucket,
  ProfileStatsCountryBucket,
  ProfileStatsCoverage,
  ProfileStatsPerson,
  ProfileStatsReviews,
  ProfileStatsResponse,
  ProfileStatsRewatches,
} from '../../services/api';
import { FilmTitle, MoviePoster, formatCalendarDate, toMovieSummary } from './InsightUI';

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

/** A sub-heading inside the panel, so the folded sections keep its chrome. */
function SubSection({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string | null;
  children: React.ReactNode;
}) {
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-wide text-white/45">{title}</p>
      {subtitle ? <p className="mt-0.5 text-[11px] leading-4 text-white/30">{subtitle}</p> : null}
      {children}
    </div>
  );
}

/**
 * The two averages a rewatch or review split produces, phrased as what they
 * are. Both sides are self-selected sets of films from the same library, so the
 * gap describes which films get revisited or written about — never what
 * revisiting or writing does to a rating.
 */
function PairedAverages({
  leftLabel,
  leftValue,
  rightLabel,
  rightValue,
  caveat,
}: {
  leftLabel: string;
  leftValue: number | null;
  rightLabel: string;
  rightValue: number | null;
  caveat: string;
}) {
  if (leftValue === null && rightValue === null) return null;
  const parts = [
    leftValue === null ? null : `${leftLabel} ${leftValue.toFixed(2)}`,
    rightValue === null ? null : `${rightLabel} ${rightValue.toFixed(2)}`,
  ].filter((part): part is string => part !== null);

  return (
    <p className="mt-2 text-[11px] leading-4 text-white/40">
      {parts.join(' · ')}
      <span className="text-white/25">{` — ${caveat}`}</span>
    </p>
  );
}

/**
 * What this member returns to. Films seen once are not listed: a film with no
 * rewatch is not a quiet entry at the bottom of a rewatch list.
 */
function RewatchSection({
  rewatches,
  journeys,
}: {
  rewatches: ProfileStatsRewatches;
  journeys?: ProfileStatsResponse['return_journeys'];
}) {
  const films = rewatches.most_rewatched ?? [];
  if (rewatches.total_rewatches === 0 && films.length === 0) return null;

  const subtitle = [
    `${formatCount(rewatches.total_rewatches)} logged across ${formatCount(rewatches.films_rewatched)} films`,
    rewatches.rewatch_rate === null
      ? null
      : `${formatRatio(rewatches.rewatch_rate)} of the library revisited`,
  ]
    .filter((part): part is string => part !== null)
    .join(' · ');

  return (
    <SubSection title="Rewatches" subtitle={subtitle}>
      {journeys && journeys.revisited_films > 0 ? (
        <p className="mt-2 rounded-lg border border-white/[0.07] bg-black/15 px-3 py-2 text-[11px] leading-5 text-white/50">
          Typically returns after{' '}
          <strong className="text-white/80">
            {formatCount(journeys.median_days_to_return ?? 0)} days
          </strong>{' '}
          across {formatCount(journeys.revisited_films)} revisited{' '}
          {journeys.revisited_films === 1 ? 'film' : 'films'}.
          {/* The paired half, and a much smaller set: only films rated on two
              separate viewings can say what the revisit did to the score. */}
          {journeys.rated_twice > 0 ? (
            <>
              {' '}Of the {formatCount(journeys.rated_twice)} rated on both viewings,{' '}
              {journeys.rating_rose} went up, {journeys.rating_fell} down and{' '}
              {journeys.rating_held} held
              {journeys.average_change !== null
                ? ` (${journeys.average_change > 0 ? '+' : ''}${journeys.average_change.toFixed(2)} on average)`
                : ''}
              .
            </>
          ) : null}
        </p>
      ) : null}
      {films.length > 0 ? (
        <ul className="mt-2 space-y-1.5">
          {films.map((film, index) => (
            <li
              key={`${film.title}-${film.year ?? 'na'}-${index}`}
              className="flex items-center gap-3 rounded-xl border border-white/5 bg-black/20 px-3 py-2"
            >
              <MoviePoster movie={toMovieSummary(film)} className="h-12 w-8" />
              <div className="min-w-0 flex-1">
                <FilmTitle film={film} />
                <p className="mt-0.5 text-[11px] leading-4 tabular-nums text-white/40">
                  {film.rating === null ? 'Unrated' : `Rated ${film.rating.toFixed(1)}`}
                </p>
              </div>
              <span
                className="shrink-0 rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-xs font-semibold tabular-nums text-white/70"
                title={`${formatCount(film.watch_count)} logged ${film.watch_count === 1 ? 'watch' : 'watches'}`}
              >
                {`×${formatCount(film.watch_count)}`}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      <PairedAverages
        leftLabel="Revisited films average"
        leftValue={rewatches.average_rating_rewatched}
        rightLabel="seen once"
        rightValue={rewatches.average_rating_once}
        caveat="two self-selected sets, not a before-and-after"
      />
    </SubSection>
  );
}

/** Writing habits, and how this member rates the films they write about. */
function ReviewSection({
  reviews,
  coverage,
}: {
  reviews: ProfileStatsReviews;
  coverage: ProfileStatsCoverage;
}) {
  const liked = reviews.most_liked ?? [];
  const byYear = reviews.reviews_by_year ?? [];
  // How much of each year's watching got written about. A rising review count
  // can just mean a busier year, so the share is the honest trend line.
  const writingRate = (reviews.writing_rate_by_year ?? []).filter(
    (row) => row.share !== null,
  );
  if (reviews.total_reviews === 0) return null;

  const subtitle = [
    `${formatCount(reviews.total_reviews)} published`,
    reviews.with_text > 0 ? `${formatCount(reviews.with_text)} with prose` : null,
    reviews.spoiler_reviews > 0 ? `${formatCount(reviews.spoiler_reviews)} flagged for spoilers` : null,
    reviews.median_length_chars === null
      ? null
      : `${formatCount(reviews.median_length_chars)} characters median`,
  ]
    .filter((part): part is string => part !== null)
    .join(' · ');

  return (
    <SubSection title="Reviews" subtitle={subtitle}>
      {reviews.longest ? (
        <p className="mt-2 text-[11px] leading-4 text-white/40">
          {`Longest: ${reviews.longest.title}${reviews.longest.year ? ` (${reviews.longest.year})` : ''}, ${formatCount(reviews.longest.length_chars)} characters`}
        </p>
      ) : null}

      {writingRate.length > 1 ? (
        <div className="mt-3">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-white/35">
            How much they write about
          </p>
          <div className="mt-2 space-y-1">
            {writingRate.map((row) => (
              <div key={row.year} className="flex items-center gap-2 text-[11px]">
                <span className="w-9 shrink-0 tabular-nums text-white/40">{row.year}</span>
                <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/10">
                  <span
                    className="block h-full rounded-full bg-cinema-500"
                    style={{ width: `${Math.max(2, (row.share ?? 0) * 100)}%` }}
                  />
                </span>
                <span
                  className="w-20 shrink-0 text-right tabular-nums text-white/45"
                  title={`${row.reviews} of ${row.films_watched} films watched`}
                >
                  {Math.round((row.share ?? 0) * 100)}% of {row.films_watched}
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {liked.length > 0 ? (
        <p className="mt-3 text-[11px] font-semibold uppercase tracking-wide text-white/35">
          Most liked
        </p>
      ) : null}
      {liked.length > 0 ? (
        <ol className="mt-2 space-y-1.5">
          {liked.map((review, index) => (
            <li
              key={`${review.title}-${review.published_date ?? index}`}
              className="flex items-center gap-2 text-sm"
            >
              <span className="min-w-0 flex-1 truncate text-white/80" title={review.title}>
                {review.title}
                {review.year ? <span className="text-white/35">{` (${review.year})`}</span> : null}
              </span>
              {review.published_date ? (
                <span className="shrink-0 text-[11px] text-white/30">
                  {formatCalendarDate(review.published_date)}
                </span>
              ) : null}
              <span
                className="w-10 shrink-0 text-right text-xs tabular-nums text-white/45"
                title={`${formatCount(review.likes_count)} likes`}
              >
                {`♥ ${formatCount(review.likes_count)}`}
              </span>
            </li>
          ))}
        </ol>
      ) : null}

      {byYear.length > 0 ? (
        <div className="mt-4">
          <BreakdownBars
            title="Reviews by year"
            subtitle="Undated reviews belong to no year and are left out"
            rows={byYear.map((entry) => ({
              id: String(entry.year),
              label: String(entry.year),
              title: String(entry.year),
              count: entry.count,
              averageRating: null,
            }))}
          />
        </div>
      ) : null}

      <PairedAverages
        leftLabel="Reviewed films average"
        leftValue={reviews.average_rating_reviewed}
        rightLabel="unreviewed"
        rightValue={reviews.average_rating_unreviewed}
        caveat="two self-selected sets, not a before-and-after"
      />
      {coverage.reviews_total > coverage.reviews_matched_to_films ? (
        <p className="mt-1 text-[11px] leading-4 text-white/25">
          {`${formatCount(coverage.reviews_matched_to_films)} of ${formatCount(coverage.reviews_total)} reviews matched a film in the library; the rest count only in the totals above.`}
        </p>
      ) : null}
    </SubSection>
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

  const marathons = stats.marathons;
  const cadence = stats.cadence;
  const releaseLag = stats.release_lag;
  const directorRuns = stats.director_runs;
  const lagYears = releaseLag?.median_lag_days != null
    ? releaseLag.median_lag_days / 365
    : null;
  // Fixed order so the row reads like a week rather than a ranking, and a
  // weekday with no watches still occupies its slot.
  const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const busiestWeekdayCount = cadence
    ? Math.max(...WEEKDAYS.map((day) => cadence.weekday_counts?.[day] ?? 0), 0)
    : 0;
  const topDirectors = stats.top_directors ?? [];
  const topActors = stats.top_actors ?? [];
  const topStudios = stats.top_studios ?? [];
  const topComposers = stats.top_composers ?? [];
  const topCinematographers = stats.top_cinematographers ?? [];
  const topEditors = stats.top_editors ?? [];
  const directorGender = stats.director_gender;
  const hasPeople = topDirectors.length > 0 || topActors.length > 0 || topStudios.length > 0
    || topComposers.length > 0 || topCinematographers.length > 0 || topEditors.length > 0;
  const hasBreakdowns = genreRows.length > 0
    || countryRows.length > 0
    || languageRows.length > 0
    || decadeRows.length > 0;

  const highlightCandidates: Array<{ label: string; name: string; ratedCount: number; average: number } | null> = [
    highestRated?.genre
      ? {
          label: 'Highest-rated genre',
          name: highestRated.genre.label,
          ratedCount: highestRated.genre.rated_count ?? highestRated.genre.count,
          average: highestRated.genre.average_rating,
        }
      : null,
    highestRated?.decade
      ? {
          label: 'Highest-rated decade',
          name: highestRated.decade.label,
          ratedCount: highestRated.decade.rated_count ?? highestRated.decade.count,
          average: highestRated.decade.average_rating,
        }
      : null,
    highestRated?.director
      ? {
          label: 'Highest-rated director',
          name: highestRated.director.name,
          ratedCount: highestRated.director.rated_count ?? highestRated.director.count,
          average: highestRated.director.average_rating,
        }
      : null,
  ];
  const highlights = highlightCandidates.filter(
    (item): item is { label: string; name: string; ratedCount: number; average: number } => item !== null,
  );

  // Rewatching and reviewing are part of the same "about this profile" story,
  // so they fold in here rather than arriving as panels of their own. A profile
  // with neither gets no divider and no empty shell.
  const rewatches = stats.rewatches;
  const reviews = stats.reviews;
  const hasRewatchSection = Boolean(
    rewatches && (rewatches.total_rewatches > 0 || (rewatches.most_rewatched?.length ?? 0) > 0),
  );
  const hasReviewSection = Boolean(reviews && reviews.total_reviews > 0);

  // One caveat for the whole panel rather than a footnote on every row.
  const enrichmentCaveat = coverage.films_total > 0
    && coverage.enrichment_ratio < ENRICHMENT_CAVEAT_THRESHOLD
    ? `Film metadata is in for ${formatRatio(coverage.enrichment_ratio)} of ${formatCount(coverage.films_total)} synced films (${formatCount(coverage.films_enriched)}), so the genre, credits, country, language and runtime figures below are drawn from that subset.`
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

      {/* Rhythm rather than volume. Two profiles with the same film count look
          nothing alike if one watches every Saturday and the other vanished for
          six weeks and binged, and the total cannot tell them apart. */}
      {cadence && cadence.active_days > 0 && busiestWeekdayCount > 0 ? (
        <div className="mt-6 rounded-xl border border-white/10 bg-black/20 px-4 py-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-sm font-semibold text-white/75">Watching rhythm</h3>
            <span className="text-[11px] text-white/40">
              {formatCount(cadence.active_days)} days with an entry
              {cadence.span_days ? ` across ${formatCount(cadence.span_days)}` : ''}
            </span>
          </div>

          <div className="mt-3 grid grid-cols-7 gap-1.5" data-testid="cadence-weekdays">
            {WEEKDAYS.map((day) => {
              const count = cadence.weekday_counts?.[day] ?? 0;
              return (
                <div key={day} className="flex flex-col items-center gap-1">
                  <div className="flex h-16 w-full items-end rounded bg-white/5">
                    <div
                      className={`w-full rounded ${
                        day === cadence.busiest_weekday ? 'bg-cinema-500' : 'bg-white/20'
                      }`}
                      style={{ height: `${Math.max((count / busiestWeekdayCount) * 100, 3)}%` }}
                    />
                  </div>
                  <span className="text-[10px] text-white/40">{day}</span>
                  <span className="text-[10px] tabular-nums text-white/55">{count}</span>
                </div>
              );
            })}
          </div>

          <p className="mt-3 text-xs text-white/55">
            {cadence.busiest_weekday ? (
              <>
                Most often a <strong className="text-white/85">{cadence.busiest_weekday}</strong>
              </>
            ) : null}
            {cadence.days_per_active_week
              ? `${cadence.busiest_weekday ? ' · ' : ''}about ${cadence.days_per_active_week} days a week while active`
              : ''}
          </p>

          {/* A gap is only worth naming when it reads as a stop rather than a
              pause, so the backend leaves this null for ordinary quiet weeks. */}
          {cadence.longest_dry_spell_days ? (
            <p className="mt-1 text-[11px] text-white/35">
              Longest silence: {formatCount(cadence.longest_dry_spell_days)} days
              {cadence.dry_spell_started ? ` from ${cadence.dry_spell_started}` : ''}
            </p>
          ) : null}
        </div>
      ) : null}

      {/* When they got to a film, which its decade cannot say: a library made
          entirely of 2020s films belongs equally to someone following new
          releases and to someone three years behind. */}
      {releaseLag && releaseLag.median_lag_days !== null && lagYears !== null ? (
        <div className="mt-6 rounded-xl border border-white/10 bg-black/20 px-4 py-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-sm font-semibold text-white/75">How soon after release</h3>
            <span className="text-[11px] text-white/40">
              {formatCount(releaseLag.measured_films)} films with a known release date
            </span>
          </div>
          <p className="mt-2 text-xs text-white/55">
            Typically{' '}
            <strong className="text-white/85">
              {lagYears >= 1
                ? `${lagYears.toFixed(1)} years`
                : `${releaseLag.median_lag_days} days`}
            </strong>{' '}
            after a film came out
            {releaseLag.lean === 'current'
              ? ' — they watch things while they are new'
              : releaseLag.lean === 'archival'
                ? ' — almost everything is back catalogue'
                : ' — a while behind, but not archival'}
            .
          </p>
          {releaseLag.fresh_share !== null && releaseLag.back_catalogue_share !== null ? (
            <p className="mt-1 text-[11px] text-white/35">
              {Math.round(releaseLag.fresh_share * 100)}% within a month of release ·{' '}
              {Math.round(releaseLag.back_catalogue_share * 100)}% at least five years old
            </p>
          ) : null}
          {releaseLag.logged_before_release > 0 ? (
            /* Stated rather than dropped silently: a festival screening and a
               mistyped diary date look identical from here. */
            <p className="mt-1 text-[11px] text-white/30">
              {formatCount(releaseLag.logged_before_release)}{' '}
              {releaseLag.logged_before_release === 1 ? 'entry was' : 'entries were'} dated before
              release and left out.
            </p>
          ) : null}
        </div>
      ) : null}

      {/* Watching a director twice in a fortnight happens about three times
          more often than shuffling the same dates would produce, so this is a
          habit rather than a by-product of watching a lot. */}
      {directorRuns && directorRuns.count > 0 && directorRuns.biggest ? (
        <div className="mt-6 rounded-xl border border-white/10 bg-black/20 px-4 py-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-sm font-semibold text-white/75">Director runs</h3>
            <span className="text-[11px] text-white/40">
              {formatCount(directorRuns.count)}{' '}
              {directorRuns.count === 1 ? 'stretch' : 'stretches'} of three or more inside a fortnight
            </span>
          </div>
          <p className="mt-2 text-xs text-white/55">
            Longest:{' '}
            <strong className="text-white/85">
              {directorRuns.biggest.films} {directorRuns.biggest.director} films
            </strong>{' '}
            over {directorRuns.biggest.days} {directorRuns.biggest.days === 1 ? 'day' : 'days'} from{' '}
            {directorRuns.biggest.started}
          </p>
          {directorRuns.biggest.titles.length > 0 ? (
            <p className="mt-1 line-clamp-2 text-[11px] text-white/35">
              {directorRuns.biggest.titles.join(' · ')}
            </p>
          ) : null}
        </div>
      ) : null}

      {marathons && marathons.count > 0 && marathons.biggest ? (
        <div className="mt-6 rounded-xl border border-white/10 bg-black/20 px-4 py-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-sm font-semibold text-white/75">Marathon days</h3>
            <span className="text-[11px] text-white/40">
              {formatCount(marathons.count)} {marathons.count === 1 ? 'day' : 'days'} with three or more films
            </span>
          </div>
          <p className="mt-2 text-xs text-white/55">
            Biggest sitting: <strong className="text-white/85">{marathons.biggest.films} films</strong>{' '}
            on {marathons.biggest.date}
            {marathons.biggest.runtime_minutes
              ? ` · ${Math.round(marathons.biggest.runtime_minutes / 60)}h`
              : ''}
          </p>
          {marathons.biggest.titles.length > 0 ? (
            <p className="mt-1 line-clamp-2 text-[11px] text-white/35">
              {marathons.biggest.titles.join(' · ')}
            </p>
          ) : null}
          {marathons.import_artifact_days > 0 ? (
            /* Stated rather than hidden: an export can date a whole backlog to
               one day, and a reader comparing this with Letterboxd should know
               those days were set aside. */
            <p className="mt-2 text-[11px] text-white/35">
              {formatCount(marathons.import_artifact_days)}{' '}
              {marathons.import_artifact_days === 1 ? 'day was' : 'days were'} excluded as bulk imports
              rather than sittings.
            </p>
          ) : null}
        </div>
      ) : null}

      {directorGender && directorGender.measured_films > 0 && directorGender.women_share !== null ? (
        <div className="mt-6 rounded-xl border border-white/10 bg-black/20 px-4 py-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-sm font-semibold text-white/75">Who directs what you watch</h3>
            {/* The denominator is stated because TMDB records no gender for
                some directors, and those films are excluded from the split
                rather than quietly assigned to one side. */}
            <span className="text-[11px] text-white/40">
              {formatCount(directorGender.measured_films)} films where TMDB records a director&rsquo;s gender
            </span>
          </div>
          <div className="mt-2.5 flex h-2 overflow-hidden rounded-full bg-white/10">
            <span
              className="bg-cinema-500"
              style={{ width: `${(directorGender.women / directorGender.measured_films) * 100}%` }}
            />
            <span
              className="bg-emerald-400/70"
              style={{ width: `${(directorGender.mixed / directorGender.measured_films) * 100}%` }}
            />
          </div>
          <p className="mt-2 text-xs text-white/50">
            <strong className="text-white/80">
              {Math.round(directorGender.women_share * 1000) / 10}%
            </strong>{' '}
            had a woman among their directors
            {directorGender.mixed > 0
              ? ` (${formatCount(directorGender.women)} solely, ${formatCount(directorGender.mixed)} co-directed)`
              : ''}
          </p>
        </div>
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
          {/* Below the line: credits stored on most enriched films that no
              panel has ever surfaced. */}
          <RankedList title="Top composers" subtitle="Scored what you watch" people={topComposers} />
          <RankedList title="Top cinematographers" subtitle="Shot what you watch" people={topCinematographers} />
          <RankedList title="Top editors" subtitle="Cut what you watch" people={topEditors} />
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
                {/* The bucket holds more films than this; the average only
                    covers the rated ones, and quoting the bucket size made a
                    three-rating average look like a twelve-film one. */}
                {highlight.average.toFixed(2)} average across {formatCount(highlight.ratedCount)} rated {highlight.ratedCount === 1 ? 'film' : 'films'}
              </p>
            </div>
          ))}
        </div>
      ) : null}

      {hasRewatchSection || hasReviewSection ? (
        <div className="mt-6 grid gap-6 border-t border-white/10 pt-5 lg:grid-cols-2">
          {hasRewatchSection && rewatches ? <RewatchSection rewatches={rewatches} journeys={stats.return_journeys} /> : null}
          {hasReviewSection && reviews ? (
            <ReviewSection reviews={reviews} coverage={coverage} />
          ) : null}
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
