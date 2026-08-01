'use client';

import React from 'react';
import { motion } from 'framer-motion';
import { useQuery } from '@tanstack/react-query';
import { Minus, Scale, TrendingDown, TrendingUp } from 'lucide-react';

import { ratingComparisonApi } from '../../services/api';
import type {
  RatingComparisonDivisiveFilm,
  RatingComparisonFilm,
  RatingComparisonLean,
} from '../../services/api';
import { FilmTitle, ListSection, MoviePoster, toMovieSummary } from './InsightUI';

/** The band the API documents for calling a profile generous or harsh. */
const LEAN_BAND = 0.15;

type Direction = 'above' | 'below' | 'level';

const DIRECTION_STYLES: Record<Direction, {
  panel: string;
  text: string;
  badge: string;
}> = {
  above: {
    panel: 'border-emerald-400/25 bg-emerald-500/[0.08]',
    text: 'text-emerald-300',
    badge: 'border-emerald-400/25 bg-emerald-500/10 text-emerald-300',
  },
  below: {
    panel: 'border-rose-400/25 bg-rose-500/[0.08]',
    text: 'text-rose-300',
    badge: 'border-rose-400/25 bg-rose-500/10 text-rose-300',
  },
  level: {
    panel: 'border-white/10 bg-white/5',
    text: 'text-white/80',
    badge: 'border-white/10 bg-white/5 text-white/60',
  },
};

const DIRECTION_ICONS: Record<Direction, typeof TrendingUp> = {
  above: TrendingUp,
  below: TrendingDown,
  level: Minus,
};

function formatCount(value: number): string {
  return value.toLocaleString();
}

/** Signed to two places, so a delta never reads as a plain rating. */
function formatSignedDelta(value: number): string {
  const rounded = Math.abs(value) < 0.005 ? 0 : value;
  return `${rounded > 0 ? '+' : rounded < 0 ? '-' : ''}${Math.abs(rounded).toFixed(2)}`;
}

function directionOf(value: number, band = 0): Direction {
  if (value > band) return 'above';
  if (value < -band) return 'below';
  return 'level';
}

/** The API's own rule, repeated only for responses that omit `lean`. */
function leanFromDelta(value: number | null): RatingComparisonLean {
  if (value === null) return 'aligned';
  const direction = directionOf(value, LEAN_BAND);
  if (direction === 'above') return 'generous';
  if (direction === 'below') return 'harsh';
  return 'aligned';
}

function raterNote(count: number): string {
  return `${formatCount(count)} ${count === 1 ? 'rater' : 'raters'}`;
}

/**
 * One crowd this film's rating is read against. The circle and Letterboxd are
 * drawn as peers: Letterboxd's average is the only outside opinion the panel
 * carries, so it sits beside the group average rather than trailing it as fine
 * print.
 */
function ReferenceChip({
  label,
  value,
  note,
  tone,
}: {
  label: string;
  value: number;
  note?: string;
  tone: 'circle' | 'letterboxd';
}) {
  const styles = tone === 'letterboxd'
    ? 'border-cinema-400/25 bg-cinema-500/10 text-cinema-200'
    : 'border-white/10 bg-white/5 text-white/65';
  return (
    <span className={`rounded-md border px-1.5 py-0.5 ${styles}`}>
      <span className="opacity-60">{label}</span>{' '}
      <span className="font-semibold">{value.toFixed(2)}</span>
      {note ? <span className="opacity-50">{` · ${note}`}</span> : null}
    </span>
  );
}

function DeltaRow({ film }: { film: RatingComparisonFilm }) {
  const direction = directionOf(film.delta);

  return (
    <li className="flex items-center gap-3 rounded-xl border border-white/5 bg-black/20 px-3 py-2">
      <MoviePoster movie={toMovieSummary(film)} className="h-12 w-8" />
      <div className="min-w-0 flex-1">
        <FilmTitle film={film} />
        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] leading-4 tabular-nums">
          <span className="font-semibold text-white/80">{film.profile_rating.toFixed(1)}</span>
          <span className="text-white/30">vs</span>
          <ReferenceChip
            label="circle"
            value={film.group_average}
            note={raterNote(film.rater_count)}
            tone="circle"
          />
          {film.letterboxd_average === null ? null : (
            <ReferenceChip label="Letterboxd" value={film.letterboxd_average} tone="letterboxd" />
          )}
        </div>
      </div>
      <span
        className={`shrink-0 rounded-lg border px-2 py-1 text-xs font-semibold tabular-nums ${DIRECTION_STYLES[direction].badge}`}
        title={`${Math.abs(film.delta).toFixed(2)} ${direction === 'below' ? 'below' : 'above'} the group average`}
      >
        {formatSignedDelta(film.delta)}
      </span>
    </li>
  );
}

function DivisiveRow({ film, username }: { film: RatingComparisonDivisiveFilm; username: string }) {
  const references = [
    // The group average excludes this profile, so it is quoted with the count
    // it was actually built from; the spread's wider count is named separately.
    `group ${film.group_average.toFixed(2)} from ${raterNote(film.group_rater_count)}`,
    `${film.rater_count} rated in total`,
    film.profile_rating === null ? `@${username} unrated` : `@${username} ${film.profile_rating.toFixed(1)}`,
  ];

  return (
    <li className="flex items-center gap-3 rounded-xl border border-white/5 bg-black/20 px-3 py-2">
      <MoviePoster movie={toMovieSummary(film)} className="h-12 w-8" />
      <div className="min-w-0 flex-1">
        <FilmTitle film={film} />
        <p className="mt-0.5 text-[11px] leading-4 tabular-nums text-white/40">
          {references.join(' · ')}
        </p>
      </div>
      <span
        className="shrink-0 rounded-lg border border-cinema-400/25 bg-cinema-500/10 px-2 py-1 text-center text-cinema-300"
        title="Widest gap between any two ratings of this film"
      >
        <span className="block text-xs font-semibold tabular-nums">
          {film.rating_spread.toFixed(2)}
        </span>
        <span className="block text-[9px] font-semibold uppercase tracking-wide text-cinema-300/70">
          spread
        </span>
      </span>
    </li>
  );
}

/** Plain-language reading of a Pearson correlation against the group. */
function describeAgreement(value: number): string {
  if (value >= 0.6) return 'closely tracks the group';
  if (value >= 0.3) return 'broadly tracks the group';
  if (value > -0.3) return 'little relation to the group';
  return 'often runs opposite the group';
}

/**
 * Where a member sits against the circle of profiles tracked alongside them:
 * the films they champion, the ones they pan, and the ones that split everyone.
 * The endpoint is optional from the page's point of view — any failure, and the
 * panel simply is not there, the same way the archive and stats panels bow out.
 */
const RatingComparisonPanel: React.FC<{ username: string; delay?: number }> = ({
  username,
  delay = 0,
}) => {
  const comparisonQuery = useQuery({
    queryKey: ['rating-comparison', username],
    queryFn: () => ratingComparisonApi.getComparison(username),
    enabled: Boolean(username),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  const data = comparisonQuery.data;

  // No hooks below this line: the panel disappears entirely when the endpoint
  // is unavailable or has nothing worth comparing.
  if (comparisonQuery.isError || !data) return null;

  const summary = data.summary;
  const coverage = data.coverage;
  const champions = data.most_generous ?? [];
  const pans = data.most_harsh ?? [];
  const divisive = data.most_divisive ?? [];

  const groupDelta = summary?.group_delta ?? null;
  const hasLists = champions.length > 0 || pans.length > 0 || divisive.length > 0;
  if (groupDelta === null && !hasLists) return null;

  // `lean` decides whether the gap is worth calling a lean at all; the wording
  // then follows the sign of the number itself, so the two can never disagree.
  const lean: RatingComparisonLean = summary?.lean ?? leanFromDelta(groupDelta);
  const headlineDirection: Direction = groupDelta === null || lean === 'aligned'
    ? 'level'
    : directionOf(groupDelta);
  const headlineStyle = DIRECTION_STYLES[headlineDirection];
  const HeadlineIcon = DIRECTION_ICONS[headlineDirection];
  const comparedFilms = formatCount(coverage?.compared_films ?? 0);

  const headline = groupDelta === null
    ? 'Not enough shared ratings to place them against their circle'
    : headlineDirection === 'level'
      ? 'Rates in line with their circle'
      : `Rates ${Math.abs(groupDelta).toFixed(2)} ${headlineDirection} their circle`;
  const headlineDetail = groupDelta === null
    ? 'The films below still show where the group splits.'
    : headlineDirection === 'level'
      ? `Effectively level with the group average across ${comparedFilms} comparable films.`
      : `Averaged over ${comparedFilms} comparable films, ${headlineDirection === 'above' ? 'more generous' : 'harsher'} than the profiles tracked alongside them.`;

  const agreement = summary?.agreement ?? null;

  // Letterboxd's own crowd average is the sole outside reference point, so it
  // gets the same treatment as the headline rather than a footnote's worth.
  const letterboxdDelta = summary?.letterboxd_delta ?? null;
  const letterboxdFilms = coverage?.letterboxd_average_films ?? 0;
  const letterboxdDirection: Direction = letterboxdDelta === null
    ? 'level'
    : directionOf(letterboxdDelta);
  const letterboxdStyle = DIRECTION_STYLES[letterboxdDirection];
  const LetterboxdIcon = DIRECTION_ICONS[letterboxdDirection];

  const minRaters = coverage?.min_raters ?? 2;
  const coverageNote = `${formatCount(coverage?.compared_films ?? 0)} of ${formatCount(coverage?.rated_films ?? 0)} rated films could be compared — a film only counts once at least ${formatCount(minRaters)} other tracked ${minRaters === 1 ? 'profile has' : 'profiles have'} rated it too.`;

  // One quiet line for the whole panel rather than a caveat on every row.
  const letterboxdPending = letterboxdFilms === 0
    ? 'Letterboxd’s own crowd average has not been fetched for these films yet, so the outside reference point is missing.'
    : null;

  return (
    <motion.section
      className="analysis-panel"
      aria-labelledby="rating-comparison-title"
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay }}
    >
      <div className="flex items-center gap-2">
        <Scale className="h-5 w-5 text-cinema-400" aria-hidden="true" />
        <h2 id="rating-comparison-title" className="text-xl font-semibold text-white">
          Rating comparison
        </h2>
      </div>
      <p className="mt-1 text-sm text-white/60">
        Where @{username} sits against the profiles tracked alongside them — and against
        Letterboxd’s own crowd — film by film.
      </p>

      <div
        className={`mt-5 flex flex-col gap-4 rounded-2xl border px-4 py-4 sm:flex-row sm:items-center sm:justify-between ${headlineStyle.panel}`}
      >
        <div className="flex min-w-0 items-start gap-3">
          <HeadlineIcon className={`mt-0.5 h-6 w-6 shrink-0 ${headlineStyle.text}`} aria-hidden="true" />
          <div className="min-w-0">
            <p className={`text-lg font-semibold ${headlineStyle.text}`}>{headline}</p>
            <p className="mt-1 text-xs leading-5 text-white/45">{headlineDetail}</p>
          </div>
        </div>
        {agreement !== null ? (
          <div className="shrink-0 sm:text-right">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-white/45">
              Agreement
            </p>
            <p className="mt-0.5 text-lg font-bold tabular-nums text-white">
              {agreement.toFixed(2)}
            </p>
            <p className="text-[11px] text-white/40">{describeAgreement(agreement)}</p>
          </div>
        ) : null}
      </div>

      {letterboxdDelta !== null ? (
        <div
          className={`mt-3 flex flex-col gap-3 rounded-2xl border px-4 py-3.5 sm:flex-row sm:items-center sm:justify-between ${letterboxdStyle.panel}`}
        >
          <div className="flex min-w-0 items-start gap-3">
            <LetterboxdIcon
              className={`mt-0.5 h-5 w-5 shrink-0 ${letterboxdStyle.text}`}
              aria-hidden="true"
            />
            <div className="min-w-0">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-white/45">
                Against Letterboxd’s crowd
              </p>
              <p className={`mt-0.5 text-base font-semibold ${letterboxdStyle.text}`}>
                {letterboxdDirection === 'level'
                  ? 'Rates in line with the wider Letterboxd audience'
                  : `Rates ${Math.abs(letterboxdDelta).toFixed(2)} ${letterboxdDirection} the wider Letterboxd audience`}
              </p>
              <p className="mt-1 text-xs leading-5 text-white/45">
                {`Averaged over the ${formatCount(letterboxdFilms)} of ${formatCount(coverage?.rated_films ?? 0)} rated films that carry Letterboxd’s own average.`}
              </p>
            </div>
          </div>
          <p
            className={`shrink-0 text-2xl font-bold tabular-nums sm:text-right ${letterboxdStyle.text}`}
          >
            {formatSignedDelta(letterboxdDelta)}
          </p>
        </div>
      ) : null}

      {hasLists ? (
        <div className="mt-6 grid gap-6 lg:grid-cols-2 xl:grid-cols-3">
          {champions.length > 0 ? (
            <ListSection title="Champions" subtitle="Rated furthest above the group">
              {champions.map((film, index) => (
                <DeltaRow key={`${film.title}-${film.year ?? 'na'}-${index}`} film={film} />
              ))}
            </ListSection>
          ) : null}
          {pans.length > 0 ? (
            <ListSection title="Pans" subtitle="Rated furthest below the group">
              {pans.map((film, index) => (
                <DeltaRow key={`${film.title}-${film.year ?? 'na'}-${index}`} film={film} />
              ))}
            </ListSection>
          ) : null}
          {divisive.length > 0 ? (
            <ListSection
              title="Most divisive"
              subtitle="Widest spread across everyone who rated them"
            >
              {divisive.map((film, index) => (
                <DivisiveRow
                  key={`${film.title}-${film.year ?? 'na'}-${index}`}
                  film={film}
                  username={username}
                />
              ))}
            </ListSection>
          ) : null}
        </div>
      ) : null}

      <p className="mt-5 text-[11px] leading-5 text-white/30">
        {[coverageNote, letterboxdPending]
          .filter((note): note is string => note !== null)
          .join(' ')}
      </p>
    </motion.section>
  );
};

export default RatingComparisonPanel;
