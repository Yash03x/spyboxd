'use client';

import React from 'react';
import { motion } from 'framer-motion';
import { useQuery } from '@tanstack/react-query';
import { Minus, Scale, TrendingDown, TrendingUp } from 'lucide-react';

import { ratingComparisonApi } from '../../services/api';
import type {
  MovieSummary,
  RatingComparisonDivisiveFilm,
  RatingComparisonFilm,
  RatingComparisonLean,
} from '../../services/api';
import { MoviePoster } from './InsightUI';

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

/**
 * TMDB publishes its averages out of 10 while every other figure on this panel
 * is out of 5. The API converts before differencing in `tmdb_delta`, but ships
 * per-film averages in TMDB's own scale, so they are halved here and the panel
 * says so once at the bottom rather than on every row.
 */
function tmdbToFiveScale(value: number): number {
  return value / 2;
}

function filmLabel(film: { title: string; year: number | null }): string {
  return film.year ? `${film.title} (${film.year})` : film.title;
}

/**
 * The comparison endpoints return flat film shells rather than the full
 * `MovieSummary` the shared poster expects; only the artwork is read from it.
 */
function toMovieSummary(film: {
  title: string;
  year: number | null;
  poster_url: string | null;
  letterboxd_url: string | null;
}): MovieSummary {
  return {
    movie_id: null,
    tmdb_id: null,
    letterboxd_slug: null,
    letterboxd_url: film.letterboxd_url,
    title: film.title,
    year: film.year,
    poster_url: film.poster_url,
  };
}

function raterNote(count: number): string {
  return `${formatCount(count)} ${count === 1 ? 'rater' : 'raters'}`;
}

function FilmTitle({ film }: { film: { title: string; year: number | null; letterboxd_url: string | null } }) {
  const label = filmLabel(film);
  return (
    <p className="truncate text-sm font-medium text-white/85" title={label}>
      {film.letterboxd_url ? (
        <a
          href={film.letterboxd_url}
          target="_blank"
          rel="noopener noreferrer"
          className="hover:text-cinema-200 hover:underline"
        >
          {label}
        </a>
      ) : (
        label
      )}
    </p>
  );
}

function DeltaRow({ film }: { film: RatingComparisonFilm }) {
  const direction = directionOf(film.delta);
  const references = [
    `${film.profile_rating.toFixed(1)} vs group ${film.group_average.toFixed(2)}`,
    raterNote(film.rater_count),
    film.letterboxd_average === null ? null : `Letterboxd ${film.letterboxd_average.toFixed(2)}`,
    film.tmdb_average === null ? null : `TMDB ${tmdbToFiveScale(film.tmdb_average).toFixed(2)}`,
  ].filter((item): item is string => item !== null);

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
    `group ${film.group_average.toFixed(2)}`,
    raterNote(film.rater_count),
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

function ListSection({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-wide text-white/45">{title}</p>
      <p className="mt-0.5 text-[11px] text-white/30">{subtitle}</p>
      <ul className="mt-2 space-y-1.5">{children}</ul>
    </div>
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

  const referenceTiles = [
    summary?.letterboxd_delta === null || summary?.letterboxd_delta === undefined
      ? null
      : {
          key: 'letterboxd',
          label: 'vs Letterboxd crowd',
          value: summary.letterboxd_delta,
          films: coverage?.letterboxd_average_films ?? 0,
          noun: "Letterboxd's crowd average",
        },
    summary?.tmdb_delta === null || summary?.tmdb_delta === undefined
      ? null
      : {
          key: 'tmdb',
          label: 'vs TMDB audience',
          value: summary.tmdb_delta,
          films: coverage?.tmdb_average_films ?? 0,
          noun: "TMDB's audience average",
        },
  ].filter((tile): tile is {
    key: string;
    label: string;
    value: number;
    films: number;
    noun: string;
  } => tile !== null);

  const minRaters = coverage?.min_raters ?? 2;
  const coverageNote = `${formatCount(coverage?.compared_films ?? 0)} of ${formatCount(coverage?.rated_films ?? 0)} rated films could be compared — a film only counts once at least ${formatCount(minRaters)} other tracked ${minRaters === 1 ? 'profile has' : 'profiles have'} rated it too.`;

  // One quiet line for the whole panel rather than a caveat on every row.
  const letterboxdPending = (coverage?.letterboxd_average_films ?? 0) === 0
    ? 'Letterboxd’s own crowd average has not been fetched for these films yet, so that reference point is missing.'
    : null;
  const showsTmdb = referenceTiles.some((tile) => tile.key === 'tmdb')
    || champions.some((film) => film.tmdb_average !== null)
    || pans.some((film) => film.tmdb_average !== null);
  const tmdbNote = showsTmdb
    ? 'TMDB averages are rescaled from its 10-point scale to match Letterboxd’s five stars.'
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
        Where @{username} sits against the profiles tracked alongside them, film by film.
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

      {referenceTiles.length > 0 ? (
        <dl className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
          {referenceTiles.map((tile) => {
            const direction = directionOf(tile.value);
            return (
              <div
                key={tile.key}
                className="rounded-xl border border-white/10 bg-white/5 px-3 py-2.5"
              >
                <dt className="text-[10px] font-semibold uppercase tracking-wide text-white/45">
                  {tile.label}
                </dt>
                <dd className={`mt-1 text-lg font-bold tabular-nums ${DIRECTION_STYLES[direction].text}`}>
                  {formatSignedDelta(tile.value)}
                  <span className="ml-1.5 text-[11px] font-medium">
                    {direction === 'level'
                      ? 'in line'
                      : direction === 'above'
                        ? 'above'
                        : 'below'}
                  </span>
                </dd>
                <p className="mt-0.5 text-[10px] leading-4 text-white/35">
                  {`${formatCount(tile.films)} films carry ${tile.noun}`}
                </p>
              </div>
            );
          })}
        </dl>
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
        {[coverageNote, letterboxdPending, tmdbNote]
          .filter((note): note is string => note !== null)
          .join(' ')}
      </p>
    </motion.section>
  );
};

export default RatingComparisonPanel;
