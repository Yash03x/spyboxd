'use client';

import React from 'react';
import { motion } from 'framer-motion';
import { useQuery } from '@tanstack/react-query';
import { Bookmark } from 'lucide-react';

import { watchlistInsightsApi } from '../../services/api';
import type {
  WatchlistGenreCount,
  WatchlistRecommendation,
  WatchlistWaitingFilm,
} from '../../services/api';
import {
  FilmTitle,
  ListSection,
  MoviePoster,
  ProfileAvatar,
  formatCalendarDate,
  formatInsightCount,
  toMovieSummary,
} from './InsightUI';

/** How much of the ranked queue to show before the reader asks for the rest. */
const QUEUE_PREVIEW = 8;

function formatDays(days: number): string {
  return `${formatInsightCount(days)} ${days === 1 ? 'day' : 'days'}`;
}

/**
 * A wait is unknown, never zero: Letterboxd only publishes an added date on
 * some watchlist surfaces, so a film without one is left unqualified rather
 * than described as freshly added.
 */
function waitNote(film: { added_date: string | null; days_waiting: number | null }): string {
  if (film.days_waiting === null) return 'Added date unknown';
  return `Waiting ${formatDays(film.days_waiting)}`;
}

function waitTitle(film: { added_date: string | null }): string | undefined {
  return film.added_date ? `Added ${formatCalendarDate(film.added_date)}` : undefined;
}

/** One member behind the circle's verdict on a queued film. */
function RaterChip({ username, rating }: { username: string; rating: number }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-md border border-white/10 bg-white/5 py-0.5 pl-0.5 pr-1.5"
      title={`@${username} rated it ${rating.toFixed(1)}`}
    >
      <ProfileAvatar username={username} size="sm" />
      <span className="max-w-24 truncate text-white/60">{username}</span>
      <span className="font-semibold tabular-nums text-white/80">{rating.toFixed(1)}</span>
    </span>
  );
}

function QueueRow({ film, rank }: { film: WatchlistRecommendation; rank: number }) {
  const references = [
    `${formatInsightCount(film.group_raters)} ${film.group_raters === 1 ? 'rater' : 'raters'}`,
    film.liked_by > 0 ? `${formatInsightCount(film.liked_by)} liked` : null,
    film.letterboxd_average !== null ? `Letterboxd ${film.letterboxd_average.toFixed(2)}` : null,
  ].filter((note): note is string => note !== null);

  return (
    <li className="flex items-start gap-3 rounded-xl border border-white/5 bg-black/20 px-3 py-2.5">
      <span className="w-4 shrink-0 pt-1 text-right text-[11px] tabular-nums text-white/25">
        {rank}
      </span>
      <MoviePoster movie={toMovieSummary(film)} className="h-16 w-11" />
      <div className="min-w-0 flex-1">
        <FilmTitle film={film} />
        <p className="mt-0.5 text-[11px] leading-4 tabular-nums text-white/40">
          {references.join(' · ')}
        </p>
        {film.raters.length > 0 ? (
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11px] leading-4">
            {film.raters.map((rater) => (
              <RaterChip key={rater.username} username={rater.username} rating={rater.rating} />
            ))}
          </div>
        ) : null}
        <p className="mt-1.5 text-[11px] leading-4 text-white/30" title={waitTitle(film)}>
          {waitNote(film)}
        </p>
      </div>
      {film.group_average !== null ? (
        <span
          className="shrink-0 rounded-lg border border-cinema-400/25 bg-cinema-500/10 px-2 py-1 text-center text-cinema-300"
          title="Average over the other tracked profiles who have seen it"
        >
          <span className="block text-sm font-semibold tabular-nums">
            {film.group_average.toFixed(2)}
          </span>
          <span className="block text-[9px] font-semibold uppercase tracking-wide text-cinema-300/70">
            circle
          </span>
        </span>
      ) : null}
    </li>
  );
}

function WaitingRow({ film }: { film: WatchlistWaitingFilm }) {
  return (
    <li className="flex items-center gap-3 rounded-xl border border-white/5 bg-black/20 px-3 py-2">
      <MoviePoster movie={toMovieSummary(film)} className="h-12 w-8" />
      <div className="min-w-0 flex-1">
        <FilmTitle film={film} />
        <p className="mt-0.5 text-[11px] leading-4 text-white/40" title={waitTitle(film)}>
          {film.added_date ? `Added ${formatCalendarDate(film.added_date)}` : 'Added date unknown'}
        </p>
      </div>
      {film.days_waiting !== null ? (
        <span className="shrink-0 text-right text-xs font-semibold tabular-nums text-white/55">
          {formatDays(film.days_waiting)}
        </span>
      ) : null}
    </li>
  );
}

function GenreSkewBars({ genres }: { genres: WatchlistGenreCount[] }) {
  const largest = genres.reduce((max, genre) => Math.max(max, genre.count), 0);

  return (
    <ul className="mt-2 space-y-1.5">
      {genres.map((genre) => (
        <li key={genre.label} className="flex items-center gap-2 text-sm">
          <span className="min-w-0 flex-1 truncate text-white/80" title={genre.label}>
            {genre.label}
          </span>
          <span className="h-1.5 w-14 shrink-0 overflow-hidden rounded-full bg-white/10">
            <span
              className="block h-full rounded-full bg-cinema-500"
              style={{ width: `${largest > 0 ? Math.max(4, Math.round((genre.count / largest) * 100)) : 4}%` }}
            />
          </span>
          <span className="w-8 shrink-0 text-right text-xs tabular-nums text-white/45">
            {formatInsightCount(genre.count)}
          </span>
        </li>
      ))}
    </ul>
  );
}

/**
 * A watchlist ranked by the circle that already saw the films.
 *
 * Letterboxd keeps a watchlist as an undifferentiated bag and can only annotate
 * it with its own site-wide average; every tracked profile's rating is already
 * held here, so each unwatched film carries what this member's own people made
 * of it. Only films with no watch record for this profile are recommended, and
 * the average behind each one excludes the member being served.
 *
 * The endpoint is optional from the page's point of view: any failure, and the
 * panel simply is not there, the same way the stats and comparison panels bow
 * out.
 */
const WatchlistPanel: React.FC<{ username: string; delay?: number }> = ({
  username,
  delay = 0,
}) => {
  const [expanded, setExpanded] = React.useState(false);
  const watchlistQuery = useQuery({
    queryKey: ['watchlist-insights', username],
    queryFn: () => watchlistInsightsApi.getInsights(username),
    enabled: Boolean(username),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  const data = watchlistQuery.data;

  // No hooks below this line: the panel disappears entirely when the endpoint
  // is unavailable or has nothing worth queueing.
  if (watchlistQuery.isError || !data) return null;

  const coverage = data.coverage;
  const recommendations = data.recommendations ?? [];
  const longestWaiting = data.longest_waiting ?? [];
  const genreSkew = data.genre_skew ?? [];
  if (recommendations.length === 0 && longestWaiting.length === 0 && genreSkew.length === 0) {
    return null;
  }

  const medianWait = data.totals?.median_days_waiting ?? null;
  const oldestWait = data.totals?.oldest_days_waiting ?? null;
  const visibleQueue = expanded ? recommendations : recommendations.slice(0, QUEUE_PREVIEW);

  const headlineStats: Array<{ key: string; label: string; value: string; hint?: string }> = [
    {
      key: 'unwatched',
      label: 'Unwatched',
      value: formatInsightCount(coverage.watchlist_films),
      hint: 'still on the watchlist',
    },
    medianWait !== null
      ? { key: 'median', label: 'Median wait', value: formatDays(medianWait) }
      : null,
    oldestWait !== null
      ? { key: 'oldest', label: 'Longest wait', value: formatDays(oldestWait) }
      : null,
  ].filter((stat): stat is { key: string; label: string; value: string; hint?: string } => (
    stat !== null
  ));

  // One qualification for the whole panel rather than a caveat on every row.
  const coverageNote = `${formatInsightCount(coverage.rated_by_group)} of ${formatInsightCount(coverage.watchlist_films)} unwatched films have a rating from another tracked profile, and only those can be ranked; ${formatInsightCount(coverage.with_letterboxd_average)} carry Letterboxd’s own average.`;
  const waitNoteForPanel = medianWait === null
    ? 'No row on this watchlist carried an added date, so the wait is unknown rather than zero.'
    : 'Rows with no added date are left out of the wait figures rather than counted as newly added.';

  return (
    <motion.section
      className="analysis-panel"
      aria-labelledby="watchlist-queue-title"
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay }}
    >
      <div className="flex items-center gap-2">
        <Bookmark className="h-5 w-5 text-cinema-400" aria-hidden="true" />
        <h2 id="watchlist-queue-title" className="text-xl font-semibold text-white">
          Watchlist queue
        </h2>
      </div>
      <p className="mt-1 text-sm text-white/60">
        What @{username} has queued but not seen, ranked by what the profiles tracked
        alongside them scored it — the number Letterboxd cannot show.
      </p>

      <dl className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-3">
        {headlineStats.map((stat) => (
          <div
            key={stat.key}
            className="rounded-xl border border-white/10 bg-white/5 px-3 py-2.5 text-center"
          >
            <dt className="text-[10px] font-semibold uppercase tracking-wide text-white/45">
              {stat.label}
            </dt>
            <dd className="mt-1 text-lg font-bold text-white">{stat.value}</dd>
            {stat.hint ? (
              <p className="mt-0.5 text-[10px] leading-4 text-white/35">{stat.hint}</p>
            ) : null}
          </div>
        ))}
      </dl>

      {recommendations.length > 0 ? (
        <div className="mt-6">
          <ListSection
            title="Watch next"
            subtitle="Highest circle average first, then the number of members behind it"
          >
            {visibleQueue.map((film, index) => (
              <QueueRow
                key={`${film.title}-${film.year ?? 'na'}-${index}`}
                film={film}
                rank={index + 1}
              />
            ))}
          </ListSection>
          {recommendations.length > QUEUE_PREVIEW ? (
            <button
              type="button"
              onClick={() => setExpanded((value) => !value)}
              className="btn-ghost mt-3 border-white/10 px-4 py-2 text-xs"
            >
              {expanded
                ? 'Show fewer'
                : `Show all ${formatInsightCount(recommendations.length)} ranked films`}
            </button>
          ) : null}
        </div>
      ) : null}

      {longestWaiting.length > 0 || genreSkew.length > 0 ? (
        <div className="mt-6 grid gap-6 lg:grid-cols-2">
          {longestWaiting.length > 0 ? (
            <ListSection title="Longest waiting" subtitle="On the list the longest, rated or not">
              {longestWaiting.map((film, index) => (
                <WaitingRow key={`${film.title}-${film.year ?? 'na'}-${index}`} film={film} />
              ))}
            </ListSection>
          ) : null}
          {genreSkew.length > 0 ? (
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-white/45">
                Piling up
              </p>
              <p className="mt-0.5 text-[11px] text-white/30">
                Genres across the whole unwatched list, not just the ranked slice
              </p>
              <GenreSkewBars genres={genreSkew} />
            </div>
          ) : null}
        </div>
      ) : null}

      <p className="mt-5 text-[11px] leading-5 text-white/30">
        {`${coverageNote} ${waitNoteForPanel}`}
      </p>
    </motion.section>
  );
};

export default WatchlistPanel;
