'use client';

import React from 'react';
import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';

import Panel from '../../components/terminal/Panel';
import Bars from '../../components/terminal/bodies/Bars';
import Diverge from '../../components/terminal/bodies/Diverge';
import Notes from '../../components/terminal/bodies/Notes';
import Posters from '../../components/terminal/bodies/Posters';
import Rows, { cell } from '../../components/terminal/bodies/Rows';
import Spark from '../../components/terminal/bodies/Spark';
import { BarsSkeleton, panelState } from '../../components/terminal/states';
import { sectionHref } from '../../components/terminal/sections';
import type {
  ActivityData,
  RecentRating,
  RecentReview,
  RecentWatchEvent,
  TagCount,
} from '../../services/api';
import {
  obscurityApi,
  peopleApi,
  profileApi,
  profileStatsApi,
  ratingComparisonApi,
  insightsApi,
  watchlistInsightsApi,
} from '../../services/api';

const MONTH_INITIAL = ['J', 'F', 'M', 'A', 'M', 'J', 'J', 'A', 'S', 'O', 'N', 'D'];

function stars(rating: number | null | undefined): string {
  if (rating === null || rating === undefined) return '—';
  const full = Math.floor(rating);
  return `${'★'.repeat(full)}${rating % 1 ? '½' : ''}` || '—';
}

function yearsBetween(from: string | null | undefined, to?: string | null): string | null {
  if (!from) return null;
  const start = new Date(from).getTime();
  const end = to ? new Date(to).getTime() : Date.now();
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) return null;
  const months = Math.round((end - start) / (1000 * 60 * 60 * 24 * 30.44));
  return `${Math.floor(months / 12)}y ${months % 12}m`;
}

export default function OnePersonTab({ subject }: { subject: string }) {
  const enabled = Boolean(subject);

  const statsQuery = useQuery({
    queryKey: ['profile-stats', subject],
    queryFn: () => profileStatsApi.getStats(subject),
    enabled,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const analysisQuery = useQuery({
    queryKey: ['profile-analysis', subject],
    queryFn: () => profileApi.getAnalysis(subject),
    enabled,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const favouritesQuery = useQuery({
    queryKey: ['people-favourites', subject],
    queryFn: () => peopleApi.getFavourites(subject),
    enabled,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const obscurityQuery = useQuery({
    queryKey: ['obscurity', subject],
    queryFn: () => obscurityApi.getObscurity(subject, 10),
    enabled,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const crowdQuery = useQuery({
    queryKey: ['rating-comparison', subject],
    queryFn: () => ratingComparisonApi.getComparison(subject),
    enabled,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const watchlistQuery = useQuery({
    queryKey: ['watchlist-insights', subject],
    queryFn: () => watchlistInsightsApi.getInsights(subject),
    enabled,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const timelineQuery = useQuery({
    queryKey: ['taste-timeline', subject],
    queryFn: () => insightsApi.getTasteTimeline([subject]),
    enabled,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const unratedQuery = useQuery({
    queryKey: ['people-unrated', subject],
    queryFn: () => peopleApi.getUnrated(subject),
    enabled,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const silentQuery = useQuery({
    queryKey: ['people-silent-fives', subject],
    queryFn: () => peopleApi.getSilentFives(subject),
    enabled,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const shiftsQuery = useQuery({
    queryKey: ['people-rewatch-shifts', subject],
    queryFn: () => peopleApi.getRewatchShifts(subject),
    enabled,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const quietQuery = useQuery({
    queryKey: ['people-quiet', subject],
    queryFn: () => peopleApi.getQuiet([subject]),
    enabled,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const stats = statsQuery.data;
  const analysis = analysisQuery.data;
  const header = analysis?.profile_header;

  const diarySpan = yearsBetween(header?.join_date ?? null);
  const watchesPerFilm =
    stats && stats.totals.films
      ? (stats.totals.films + stats.totals.rewatches) / stats.totals.films
      : null;

  const monthly = (analysis?.monthly_stats ?? []).map((entry: ActivityData) => {
    const month = Number(entry.month?.slice(5, 7) ?? '1') - 1;
    return {
      label: MONTH_INITIAL[Number.isNaN(month) ? 0 : month] ?? '?',
      value: entry.movies_watched,
      inner: entry.unique_movies ?? undefined,
      display: entry.movies_watched === 0 ? '—' : String(entry.movies_watched),
      partial: entry.is_partial,
      hint: `${entry.month}${entry.is_partial ? ', month to date' : ''}: ${entry.movies_watched} watches`,
    };
  });

  // Their last ten, merged from three separate lists. Three panels asking
  // "what did they just do" is one question answered three times.
  const lastTen = React.useMemo(() => {
    type Entry = { kind: string; what: string; when: string | null; star: number | null };
    const entries: Entry[] = [];
    (analysis?.recent_watching_trend ?? []).forEach((watch: RecentWatchEvent) =>
      entries.push({
        kind: watch.is_rewatch ? 'rewatch' : 'watch',
        what: watch.movie_title,
        when: watch.watched_date,
        star: watch.rating,
      }),
    );
    (analysis?.recent_reviews ?? []).forEach((review: RecentReview) =>
      entries.push({
        kind: 'review',
        what: review.movie_title,
        when: review.published_date,
        star: review.rating,
      }),
    );
    (analysis?.recent_ratings ?? []).forEach((rating: RecentRating) =>
      entries.push({
        kind: 'rating',
        what: rating.movie_title,
        when: rating.watched_date,
        star: rating.rating,
      }),
    );
    return entries
      .filter((entry) => entry.when)
      .sort((a, b) => new Date(b.when!).getTime() - new Date(a.when!).getTime())
      .slice(0, 10);
  }, [analysis]);

  const timelinePoints = timelineQuery.data?.yearly ?? [];

  return (
    <>
      <Panel
        title={`@${subject.toUpperCase()}`}
        src="profiles · rollups"
        stats={
          stats
            ? [
                { big: stats.totals.films.toLocaleString(), unit: 'FILMS', tone: 'var(--accent)' },
                {
                  big: stats.totals.average_rating ? stats.totals.average_rating.toFixed(2) : '—',
                  unit: 'AVG',
                },
                { big: stats.reviews.total_reviews.toLocaleString(), unit: 'REVIEWS' },
                { big: diarySpan ?? '—', unit: 'OF DIARY' },
                { big: watchesPerFilm ? watchesPerFilm.toFixed(2) : '—', unit: 'WATCHES / FILM' },
              ]
            : undefined
        }
        caveat={
          stats
            ? `${stats.coverage.films_enriched.toLocaleString()} of ${stats.coverage.films_total.toLocaleString()} films carry TMDB metadata — every genre, country and credit panel below is capped by that. Switching person switches the whole tab.`
            : undefined
        }
      >
        {panelState({
          isLoading: statsQuery.isLoading,
          error: statsQuery.error,
          severity: 'fatal',
          errorTitle: 'This profile could not be loaded',
          errorBody: 'Nothing on this tab can be shown without it.',
          onRetry: () => statsQuery.refetch(),
        })}
      </Panel>

      <Panel
        title="THEIR FOUR FAVOURITES"
        src="profile_favorite_movies"
        blurb="Four slots, chosen deliberately, changed rarely. The most considered statement a Letterboxd member makes about themselves."
        caveat={favouritesQuery.data?.caveat}
      >
        {panelState({
          isLoading: favouritesQuery.isLoading,
          error: favouritesQuery.error,
          isEmpty: (favouritesQuery.data?.favourites.length ?? 0) === 0,
          onRetry: () => favouritesQuery.refetch(),
          errorTitle: 'Favourites could not be loaded',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'No favourites set',
            body: 'This member has not chosen any of the four slots, or the profile surface that carries them was never read.',
          },
        }) ?? (
          <Posters
            items={(favouritesQuery.data?.favourites ?? []).map((film) => ({
              title: film.year ? `${film.title} (${film.year})` : film.title,
              posterUrl: film.poster_url,
              href: film.letterboxd_url ?? undefined,
              sub: `slot ${film.position}`,
              right: stars(film.rating),
              tone: 'var(--accent)',
              rightCaption: film.rating === null ? 'not rated' : undefined,
            }))}
          />
        )}
      </Panel>

      <Panel
        title="FAVOURITE SLOTS, CHANGED"
        src="profile_data_changes · entity_type favorite"
        blurb="A swap is the most considered edit anybody makes here."
        caveat={favouritesQuery.data?.caveat}
      >
        {panelState({
          isLoading: favouritesQuery.isLoading,
          error: favouritesQuery.error,
          isEmpty: (favouritesQuery.data?.changes.length ?? 0) === 0,
          severity: 'quiet',
          onRetry: () => favouritesQuery.refetch(),
          errorTitle: 'Favourite history could not be loaded',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'No swap observed yet',
            body: 'Letterboxd publishes no history for the four slots. A change is only visible as the difference between two authoritative reads, so this fills from the second refresh onward.',
            cta: { label: 'SEE THE REFRESH LEDGER', href: sectionHref('data', 'refreshes') },
          },
        }) ?? (
          <Rows
            columns="66px minmax(0,1fr) 74px"
            head={['WHEN', 'WHAT', ['KIND', 'right']]}
            rows={(favouritesQuery.data?.changes ?? []).map((change) => ({
              cells: [
                cell(
                  change.detected_at
                    ? new Date(change.detected_at).toLocaleDateString('en-GB', {
                        month: 'short',
                        year: 'numeric',
                      })
                    : '—',
                  { size: '10px', tone: 'var(--ink3)' },
                ),
                cell(change.year ? `${change.title} (${change.year})` : change.title, {
                  font: 's',
                  size: '10.5px',
                  wrap: true,
                }),
                cell(change.change_type.replace('favorite_', ''), {
                  align: 'right',
                  size: '10px',
                  tone: change.change_type.endsWith('removed') ? 'var(--bad)' : 'var(--ok)',
                }),
              ],
            }))}
          />
        )}
      </Panel>

      <Panel
        title="THEY KEEP GOING BACK"
        src="profile_films.watch_count"
        blurb="Nine watches across ten years is a different fact from nine in a month, and the count alone cannot separate them."
        stats={
          stats
            ? [
                { big: stats.rewatches.films_rewatched.toLocaleString(), unit: 'FILMS REVISITED' },
                { big: stats.rewatches.total_rewatches.toLocaleString(), unit: 'REWATCHES' },
              ]
            : undefined
        }
        caveat="A rewatch count of one is real: Letterboxd allows a rewatch flag when the original viewing was never logged, and the missing viewing is not invented here."
      >
        {panelState({
          isLoading: statsQuery.isLoading,
          error: statsQuery.error,
          isEmpty: (stats?.rewatches.most_rewatched.length ?? 0) === 0,
          onRetry: () => statsQuery.refetch(),
          errorTitle: 'Rewatches could not be loaded',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'Nothing revisited yet',
            body: 'No film in this library carries more than one watch.',
          },
        }) ?? (
          <Posters
            items={(stats?.rewatches.most_rewatched ?? []).map((film) => ({
              title: film.year ? `${film.title} (${film.year})` : film.title,
              posterUrl: film.poster_url,
              href: film.letterboxd_url ?? undefined,
              sub: stars(film.rating),
              right: String(film.watch_count),
              tone: 'var(--accent)',
              rightCaption: 'watches',
            }))}
          />
        )}
      </Panel>

      <Panel
        title="HOW SOON AFTER RELEASE"
        src="movies.release_year × watched_date"
        blurb="Whether they watch things as they come out or catch up years later. This decides how much of Tonight should be new releases."
        stats={
          stats?.release_lag.median_lag_days !== null && stats?.release_lag.median_lag_days !== undefined
            ? [
                {
                  big: `${(stats.release_lag.median_lag_days / 365).toFixed(1)} years`,
                  unit: 'TYPICAL WAIT',
                  tone: 'var(--accent)',
                },
                {
                  big: stats.release_lag.fresh_share !== null
                    ? `${Math.round(stats.release_lag.fresh_share * 100)}%`
                    : '—',
                  unit: 'WITHIN A MONTH OF RELEASE',
                },
                {
                  big: stats.release_lag.back_catalogue_share !== null
                    ? `${Math.round(stats.release_lag.back_catalogue_share * 100)}%`
                    : '—',
                  unit: 'AT LEAST FIVE YEARS OLD',
                },
              ]
            : undefined
        }
        caveat={
          stats
            ? `Measured over ${stats.release_lag.measured_films.toLocaleString()} films with a known release date.${
                stats.release_lag.logged_before_release
                  ? ` ${stats.release_lag.logged_before_release} entries were dated before release and left out of the median — festival screenings and bad dates — rather than hidden.`
                  : ''
              }`
            : undefined
        }
      >
        {panelState({
          isLoading: statsQuery.isLoading,
          error: statsQuery.error,
          isEmpty: (stats?.release_lag.measured_films ?? 0) === 0,
          onRetry: () => statsQuery.refetch(),
          errorTitle: 'Release lag could not be computed',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'Not enough dated films',
            body: 'This needs both a release year and a watch date on the same film. Neither is guessed at.',
          },
        })}
      </Panel>

      <Panel
        title="THEIR YEAR, MONTH BY MONTH"
        src="watch_events.watched_date"
        blurb="One profile rather than the group. The lighter block is films they had never logged before."
      >
        {panelState({
          isLoading: analysisQuery.isLoading,
          error: analysisQuery.error,
          isEmpty: monthly.length === 0,
          onRetry: () => analysisQuery.refetch(),
          errorTitle: 'Monthly activity could not be loaded',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'No dated watches this year',
            body: 'Undated entries cannot be placed on a month and are excluded rather than guessed at.',
          },
        }) ?? <Spark items={monthly} />}
      </Panel>

      <Panel
        title="THEIR RHYTHM"
        src="watch_events.watched_date · cadence"
        blurb="Volume says how much; rhythm says how. The same film count reads differently if it arrived weekly or in two binges either side of a silence."
        stats={
          stats
            ? [
                {
                  big: stats.cadence.active_days.toLocaleString(),
                  unit: 'DAYS WITH AN ENTRY',
                  tone: 'var(--accent)',
                },
                {
                  big: stats.cadence.days_per_active_week
                    ? stats.cadence.days_per_active_week.toFixed(1)
                    : '—',
                  unit: 'DAYS PER ACTIVE WEEK',
                },
                { big: stats.cadence.busiest_weekday ?? '—', unit: 'MOST OFTEN A' },
              ]
            : undefined
        }
        caveat={
          stats
            ? `${stats.cadence.active_days.toLocaleString()} days with an entry across ${
                stats.cadence.span_days ? `${stats.cadence.span_days.toLocaleString()} days` : 'the imported span'
              }.${
                stats.cadence.longest_dry_spell_days
                  ? ` Longest silence: ${stats.cadence.longest_dry_spell_days} days${
                      stats.cadence.dry_spell_started ? ` from ${stats.cadence.dry_spell_started}` : ''
                    } — a run of quiet weeks is not the same as a slow one, so it is named rather than averaged away.`
                  : ''
              }`
            : undefined
        }
      >
        {panelState({
          isLoading: statsQuery.isLoading,
          error: statsQuery.error,
          isEmpty: (stats?.cadence.active_days ?? 0) === 0,
          onRetry: () => statsQuery.refetch(),
          errorTitle: 'Cadence could not be computed',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'No dated entries',
            body: 'Rhythm needs dates. An undated library has a volume but no shape.',
          },
          skeleton: <BarsSkeleton rows={7} />,
        }) ?? (
          <Bars
            items={['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((day) => ({
              name: day,
              weight: stats?.cadence.weekday_counts?.[day] ?? 0,
              value: String(stats?.cadence.weekday_counts?.[day] ?? 0),
            }))}
          />
        )}
      </Panel>

      <Panel
        title="THEIR LAST TEN"
        src="watch_events · ratings · reviews"
        blurb="Watches, ratings and reviews in one stream. Three lists asking what they just did is the same question answered three times."
      >
        {panelState({
          isLoading: analysisQuery.isLoading,
          error: analysisQuery.error,
          isEmpty: lastTen.length === 0,
          onRetry: () => analysisQuery.refetch(),
          errorTitle: 'Recent activity could not be loaded',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'Nothing dated recently',
            body: 'Only dated entries can be ordered into a stream.',
          },
        }) ?? (
          <Rows
            columns="52px minmax(0,1fr) 62px 44px"
            head={['KIND', 'WHAT', ['WHEN', 'right'], ['★', 'right']]}
            rows={lastTen.map((entry) => ({
              cells: [
                cell(entry.kind, { size: '9.5px', tone: 'var(--muted)' }),
                cell(entry.what, { font: 's', size: '10.5px', wrap: true }),
                cell(
                  entry.when
                    ? new Date(entry.when).toLocaleDateString('en-GB', {
                        day: '2-digit',
                        month: 'short',
                      })
                    : '—',
                  { align: 'right', size: '10px', tone: 'var(--muted)' },
                ),
                cell(entry.star === null ? '—' : entry.star.toFixed(1), {
                  align: 'right',
                  tone: 'var(--accent)',
                }),
              ],
            }))}
          />
        )}
      </Panel>

      <Panel
        title="HOW FAR OFF THE MAP THEY WATCH"
        src="movies popularity percentile"
        blurb="Share of their library that sits outside the most-watched films. Was called the obscurity index, which told nobody anything."
        stats={
          obscurityQuery.data
            ? [
                {
                  big: obscurityQuery.data.index.median_rating_count?.toLocaleString() ?? '—',
                  unit: 'TYPICAL AUDIENCE',
                  tone: 'var(--accent)',
                },
                {
                  big: obscurityQuery.data.index.percentile_vs_group !== null
                    ? `${Math.round(obscurityQuery.data.index.percentile_vs_group)}`
                    : '—',
                  unit: 'PERCENTILE VS GROUP',
                },
                { big: (obscurityQuery.data.index.lean ?? '—').toUpperCase(), unit: 'LEAN' },
              ]
            : undefined
        }
        caveat={
          obscurityQuery.data
            ? `Measured over ${obscurityQuery.data.coverage.films_with_rating_count.toLocaleString()} of ${obscurityQuery.data.coverage.rated_films.toLocaleString()} rated films that carry an audience count. Films the backfill has not reached are excluded rather than counted as an audience of zero, which would flatter everybody.`
            : undefined
        }
      >
        {panelState({
          isLoading: obscurityQuery.isLoading,
          error: obscurityQuery.error,
          isEmpty: (obscurityQuery.data?.most_obscure.length ?? 0) === 0,
          onRetry: () => obscurityQuery.refetch(),
          errorTitle: 'Off-the-map score is unavailable',
          errorBody: 'It reads the enrichment cache, which did not answer.',
          empty: {
            title: 'Not enough enriched films',
            body: 'A popularity percentile needs TMDB metadata. Unmatched films are excluded rather than counted as obscure, which would flatter everybody.',
            cta: { label: 'SEE THE MATCH RATE', href: sectionHref('films', 'gaps') },
          },
        }) ?? (
          <Posters
            items={(obscurityQuery.data?.most_obscure ?? []).slice(0, 6).map((film) => ({
              title: film.year ? `${film.title} (${film.year})` : film.title,
              posterUrl: film.poster_url,
              href: film.letterboxd_url ?? undefined,
              sub: `${film.rating_count?.toLocaleString() ?? 'audience unknown'} ratings on Letterboxd`,
              right: film.profile_rating.toFixed(1),
              tone: 'var(--accent)',
              rightCaption: 'their star',
            }))}
          />
        )}
      </Panel>

      <Panel
        title="WHERE THEY SIT AGAINST THE CROWD"
        src="ratings × crowd average"
        blurb="Where their star lands against the same film's average across the rest of the circle. The two tails, not a single averaged number that would cancel them out."
        stats={
          crowdQuery.data
            ? [
                {
                  big: crowdQuery.data.summary.group_delta !== null
                    ? `${crowdQuery.data.summary.group_delta > 0 ? '+' : '−'}${Math.abs(crowdQuery.data.summary.group_delta).toFixed(2)}`
                    : '—',
                  unit: 'VS THE CIRCLE',
                  tone:
                    (crowdQuery.data.summary.group_delta ?? 0) < 0 ? 'var(--bad)' : 'var(--ok)',
                },
                { big: (crowdQuery.data.summary.lean ?? '—').toUpperCase(), unit: 'LEAN' },
                {
                  big: crowdQuery.data.summary.agreement !== null
                    ? crowdQuery.data.summary.agreement.toFixed(2)
                    : '—',
                  unit: 'CORRELATION',
                },
              ]
            : undefined
        }
        caveat={
          crowdQuery.data
            ? `${crowdQuery.data.coverage.compared_films.toLocaleString()} of ${crowdQuery.data.coverage.rated_films.toLocaleString()} rated films are comparable — a film only counts once ${crowdQuery.data.coverage.min_raters} or more other tracked profiles have rated it.`
            : undefined
        }
      >
        {panelState({
          isLoading: crowdQuery.isLoading,
          error: crowdQuery.error,
          isEmpty: (crowdQuery.data?.coverage.compared_films ?? 0) === 0,
          onRetry: () => crowdQuery.refetch(),
          errorTitle: 'Crowd comparison could not be loaded',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'Not enough compared films',
            body: 'A film is only comparable once enough other tracked profiles have rated it. Widen the monitored set and this fills in.',
            cta: { label: 'CHOOSE WHO TO MONITOR', href: sectionHref('data', 'profiles') },
          },
        }) ?? (
          <Diverge
            label="FILM"
            axis="HARSHER ← → KINDER"
            labelWidth="minmax(96px,1.2fr)"
            items={[
              ...(crowdQuery.data?.most_harsh ?? []).slice(0, 4),
              ...(crowdQuery.data?.most_generous ?? []).slice(0, 4),
            ]
              .sort((a, b) => a.delta - b.delta)
              .map((film) => ({
                name: film.title,
                value: film.delta,
                n: film.rater_count,
              }))}
          />
        )}
      </Panel>

      <Panel
        title="THEIR QUEUE, RANKED BY THEIR CIRCLE"
        src="watchlist_items × ratings"
        blurb="What is waiting, ordered by how the people they follow rated it rather than by when it was added."
        caveat={
          watchlistQuery.data
            ? `${watchlistQuery.data.coverage.rated_by_group.toLocaleString()} of ${watchlistQuery.data.coverage.watchlist_films.toLocaleString()} unwatched queue entries have been rated by somebody else tracked. The rest are waiting on evidence, not on this panel.`
            : undefined
        }
      >
        {panelState({
          isLoading: watchlistQuery.isLoading,
          error: watchlistQuery.error,
          isEmpty: (watchlistQuery.data?.recommendations.length ?? 0) === 0,
          onRetry: () => watchlistQuery.refetch(),
          errorTitle: 'Their queue could not be loaded',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'Nothing in the queue we can rank',
            body: 'Either the watchlist is private, or nobody else tracked has rated anything on it.',
          },
        }) ?? (
          <Posters
            items={(watchlistQuery.data?.recommendations ?? []).slice(0, 6).map((film) => ({
              title: film.year ? `${film.title} (${film.year})` : film.title,
              posterUrl: film.poster_url,
              href: film.letterboxd_url ?? undefined,
              sub: [
                `${film.group_raters} in their circle rated it`,
                film.crowd_ceiling == null
                  ? null
                  : `${Math.round(film.crowd_ceiling * 100)}% rated it 4.5+`,
                // Only shown where the crowd genuinely splits. A film almost
                // nobody dislikes has not earned a downside note.
                film.crowd_floor != null && film.crowd_floor >= 0.2
                  ? `${Math.round(film.crowd_floor * 100)}% rated it 2.0 or below`
                  : null,
                film.days_waiting == null ? null : `queued ${Math.round(film.days_waiting / 365)}y`,
              ]
                .filter(Boolean)
                .join(' · '),
              right: film.group_average === null ? '—' : film.group_average.toFixed(1),
              tone: (film.group_average ?? 0) >= 4 ? 'var(--ok)' : 'var(--accent)',
              rightCaption: film.group_raters < 3 ? 'thin evidence' : 'circle avg',
            }))}
          />
        )}
      </Panel>

      <Panel
        title="GENRES, DECADES, COUNTRIES, CREDITS"
        src="movie_enrichments"
        blurb="Was Taste DNA. Genres shown; decades, countries and credits are the same shape from the same cache."
        caveat={
          stats
            ? `Capped by enrichment: ${Math.round(stats.coverage.enrichment_ratio * 100)}% of their films carry TMDB metadata, and the rest are excluded rather than counted as "none".`
            : undefined
        }
      >
        {panelState({
          isLoading: statsQuery.isLoading,
          error: statsQuery.error,
          isEmpty: (stats?.genres.length ?? 0) === 0,
          onRetry: () => statsQuery.refetch(),
          errorTitle: 'Taste breakdown could not be loaded',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'No metadata dimensions ready yet',
            body: 'TMDB enrichment has not reached enough of this library.',
            cta: { label: 'SEE THE MATCH RATE', href: sectionHref('films', 'gaps') },
          },
          skeleton: <BarsSkeleton rows={8} />,
        }) ?? (
          <Bars
            items={(stats?.genres ?? []).slice(0, 8).map((bucket) => ({
              name: bucket.label,
              weight: bucket.count,
              value: bucket.count.toLocaleString(),
              sub: bucket.average_rating === null ? '—' : bucket.average_rating.toFixed(1),
            }))}
          />
        )}
      </Panel>

      <Panel
        title="TAGS AND WHAT THEY JUST WATCHED"
        src="profile_films.tags"
        blurb="Tags are private vocabulary, invented by one person for themselves."
        caveat="Tags are read from the diary surface only. A profile last read by an older importer carries none, which is not the same as using none."
      >
        {panelState({
          isLoading: analysisQuery.isLoading,
          error: analysisQuery.error,
          isEmpty: (analysis?.tag_counts?.length ?? 0) === 0,
          onRetry: () => analysisQuery.refetch(),
          errorTitle: 'Tags could not be loaded',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'No tags synced',
            body: 'Tags only appear on films this member tagged on Letterboxd, and only when the diary surface was read by a current importer.',
          },
          skeleton: <BarsSkeleton rows={5} />,
        }) ?? (
          <Bars
            items={(analysis?.tag_counts ?? []).slice(0, 8).map((tag: TagCount) => ({
              name: tag.tag,
              weight: tag.count,
              value: tag.count.toLocaleString(),
            }))}
          />
        )}
      </Panel>

      <Panel
        title="GETTING HARSHER OR SOFTER"
        src="ratings × watched_date year"
        blurb="Their average by year. A drifting baseline changes what every gap figure in Overlaps actually means."
        caveat={
          timelineQuery.data
            ? `${timelineQuery.data.summary.rated_dated_events.toLocaleString()} dated rated events across ${timelineQuery.data.summary.years} years. ${timelineQuery.data.summary.undated_known_watches.toLocaleString()} known watches carry no date and sit in no year at all.`
            : undefined
        }
      >
        {panelState({
          isLoading: timelineQuery.isLoading,
          error: timelineQuery.error,
          isEmpty: timelinePoints.length === 0,
          onRetry: () => timelineQuery.refetch(),
          errorTitle: 'The timeline could not be loaded',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'No dated periods',
            body: 'This selection has no dated rated events for the requested grain.',
          },
        }) ?? (
          <Spark
            items={timelinePoints.map((point) => {
              const own = point.per_profile.find((entry) => entry.username === subject);
              return {
                label: String(point.year).slice(2),
                // Hundredths of a star: the whole range of a drifting baseline
                // is a few tenths, and a 0-5 axis would flatten it to nothing.
                value: Math.round((own?.average_rating ?? 0) * 100),
                display: own?.average_rating ? own.average_rating.toFixed(2) : '—',
                hint: `${point.label}: average ${own?.average_rating?.toFixed(2) ?? '—'} over ${own?.rated_events ?? 0} rated events`,
              };
            })}
            max={500}
          />
        )}
      </Panel>

      <Panel
        title="REVIEW LENGTH AND SPOILER RATE"
        src="reviews.review_text · contains_spoilers"
        stats={
          stats
            ? [
                { big: stats.reviews.total_reviews.toLocaleString(), unit: 'REVIEWS' },
                {
                  big: stats.reviews.median_length_chars
                    ? stats.reviews.median_length_chars.toLocaleString()
                    : '—',
                  unit: 'MEDIAN CHARS',
                },
                {
                  big: stats.reviews.total_reviews
                    ? `${Math.round((stats.reviews.spoiler_reviews / stats.reviews.total_reviews) * 100)}%`
                    : '—',
                  unit: 'FLAG SPOILERS',
                },
              ]
            : undefined
        }
        caveat={
          stats
            ? `${stats.reviews.with_text.toLocaleString()} of ${stats.reviews.total_reviews.toLocaleString()} reviews carry prose. A rating logged bare has no length, not a length of zero.`
            : undefined
        }
      >
        {panelState({
          isLoading: statsQuery.isLoading,
          error: statsQuery.error,
          isEmpty: (stats?.reviews.total_reviews ?? 0) === 0,
          onRetry: () => statsQuery.refetch(),
          errorTitle: 'Review stats could not be loaded',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'No reviews imported',
            body: 'This member has written none, or the review surface was never read.',
          },
        })}
      </Panel>

      <Panel
        title="WATCHED BUT NEVER RATED"
        src="profile_films × ratings absence"
        blurb="A hole in the evidence rather than an opinion. Every comparison in People and Overlaps skips these silently."
        stats={
          unratedQuery.data
            ? [
                { big: unratedQuery.data.unrated.toLocaleString(), unit: 'UNRATED', tone: 'var(--accent)' },
                {
                  big: unratedQuery.data.share !== null
                    ? `${Math.round(unratedQuery.data.share * 100)}%`
                    : '—',
                  unit: 'OF THEIR LIBRARY',
                },
              ]
            : undefined
        }
        caveat={unratedQuery.data?.caveat}
      >
        {panelState({
          isLoading: unratedQuery.isLoading,
          error: unratedQuery.error,
          isEmpty: (unratedQuery.data?.films.length ?? 0) === 0,
          onRetry: () => unratedQuery.refetch(),
          errorTitle: 'Unrated films could not be loaded',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'Everything is rated',
            body: 'Every film in this library carries a star. There is no hole to show.',
          },
        }) ?? (
          <Posters
            items={(unratedQuery.data?.films ?? []).slice(0, 6).map((film) => ({
              title: film.year ? `${film.title} (${film.year})` : film.title,
              posterUrl: film.poster_url,
              href: film.letterboxd_url ?? undefined,
              sub: film.latest_watched_date
                ? `logged ${new Date(film.latest_watched_date).toLocaleDateString('en-GB', { month: 'short', year: 'numeric' })}${film.has_review ? ' · reviewed, not rated' : ' · no rating, no review'}`
                : 'no date on this entry',
              right: '—',
              tone: 'var(--muted)',
              rightCaption: 'unrated',
            }))}
          />
        )}
      </Panel>

      <Panel
        title="CHANGED THEIR MIND ON A REWATCH"
        src="profile_data_changes.rating_changed"
        blurb="A rating that moved between two reads of the same profile."
        stats={
          shiftsQuery.data && shiftsQuery.data.count
            ? [
                { big: shiftsQuery.data.rose, unit: 'WENT UP', tone: 'var(--ok)' },
                { big: shiftsQuery.data.fell, unit: 'WENT DOWN', tone: 'var(--bad)' },
              ]
            : undefined
        }
        caveat={shiftsQuery.data?.caveat}
      >
        {panelState({
          isLoading: shiftsQuery.isLoading,
          error: shiftsQuery.error,
          isEmpty: (shiftsQuery.data?.shifts.length ?? 0) === 0,
          severity: 'quiet',
          onRetry: () => shiftsQuery.refetch(),
          errorTitle: 'Rating changes could not be loaded',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'Nothing changed yet',
            body: 'A rating change is only detectable between two authoritative reads. A first import is the baseline and emits nothing — this stays empty by design until the second refresh.',
            cta: { label: 'SEE THE REFRESH LEDGER', href: sectionHref('data', 'refreshes') },
          },
        }) ?? (
          <Rows
            columns="minmax(0,1fr) 78px 52px"
            head={['FILM', ['THEN → NOW', 'right'], ['SHIFT', 'right']]}
            rows={(shiftsQuery.data?.shifts ?? []).map((shift) => ({
              cells: [
                cell(shift.year ? `${shift.title} (${shift.year})` : shift.title, {
                  font: 's',
                  tone: 'var(--ink)',
                  wrap: true,
                }),
                cell(`${shift.before.toFixed(1)} → ${shift.after.toFixed(1)}`, {
                  align: 'right',
                  size: '10.5px',
                  tone: 'var(--muted)',
                }),
                cell(`${shift.shift > 0 ? '+' : '−'}${Math.abs(shift.shift).toFixed(1)}`, {
                  align: 'right',
                  tone: shift.shift > 0 ? 'var(--ok)' : 'var(--bad)',
                }),
              ],
            }))}
          />
        )}
      </Panel>

      <Panel
        title="LOVED IT, SAID NOTHING"
        isNew
        src="ratings.rating × reviews absence"
        blurb="Five stars with no review text. The films that meant enough not to write about — invisible to every panel that reads review bodies."
        caveat={silentQuery.data?.caveat}
      >
        {panelState({
          isLoading: silentQuery.isLoading,
          error: silentQuery.error,
          isEmpty: (silentQuery.data?.films.length ?? 0) === 0,
          onRetry: () => silentQuery.refetch(),
          errorTitle: 'Silent fives could not be loaded',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'Nothing at the top of the scale is silent',
            body: 'Every five-star rating here carries a review, or there are no five-star ratings yet.',
          },
        }) ?? (
          <Posters
            items={(silentQuery.data?.films ?? []).slice(0, 6).map((film) => ({
              title: film.year ? `${film.title} (${film.year})` : film.title,
              posterUrl: film.poster_url,
              href: film.letterboxd_url ?? undefined,
              sub: `rated ${stars(film.rating)} · ${film.watch_count} watch${film.watch_count === 1 ? '' : 'es'} · no review`,
              right: stars(film.rating),
              tone: 'var(--accent)',
              rightCaption: 'never written about',
            }))}
          />
        )}
      </Panel>

      <Panel
        title="GONE QUIET"
        isNew
        src="watch_events gaps per profile"
        blurb="Longest current silence measured against this profile's own rhythm, not a global threshold."
        caveat={quietQuery.data?.caveat}
      >
        {panelState({
          isLoading: quietQuery.isLoading,
          error: quietQuery.error,
          isEmpty: (quietQuery.data?.profiles.length ?? 0) === 0,
          onRetry: () => quietQuery.refetch(),
          errorTitle: 'Silence could not be measured',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'No dated watches',
            body: 'There is no rhythm to measure a silence against.',
          },
        }) ?? (
          <Rows
            columns="minmax(0,1fr) 66px 66px minmax(0,1.2fr)"
            head={['PROFILE', ['SILENT', 'right'], ['USUAL GAP', 'right'], 'READ']}
            rows={(quietQuery.data?.profiles ?? []).map((entry) => {
              const tone =
                entry.multiple === null
                  ? 'var(--muted)'
                  : entry.multiple >= 3
                    ? 'var(--bad)'
                    : entry.multiple >= 2
                      ? 'var(--accent)'
                      : 'var(--ok)';
              return {
                cells: [
                  cell(`@${entry.username}`),
                  cell(entry.silent_days === null ? '—' : `${entry.silent_days} days`, {
                    align: 'right',
                    tone,
                  }),
                  cell(entry.usual_gap_days === null ? '—' : `${entry.usual_gap_days} days`, {
                    align: 'right',
                    size: '10px',
                    tone: 'var(--muted)',
                  }),
                  cell(entry.read, { font: 's', size: '10px', tone: 'var(--dim)', wrap: true }),
                ],
              };
            })}
          />
        )}
      </Panel>

      <Panel
        title="WHERE THE CROWD WAS DIVIDED"
        src="ratings histogram spread"
        blurb="Films this person rated that the wider crowd could not agree on. Contested taste is a different claim from obscure taste — plenty of people saw these; they just split."
        stats={
          obscurityQuery.data?.contested_taste
            ? [
                {
                  big: obscurityQuery.data.contested_taste.contested_films.toLocaleString(),
                  unit: 'CONTESTED',
                  tone: 'var(--accent)',
                },
                {
                  big: obscurityQuery.data.contested_taste.agreed_films.toLocaleString(),
                  unit: 'AGREED ON',
                },
                {
                  big:
                    obscurityQuery.data.contested_taste.lean_ratio === null
                      ? '—'
                      : obscurityQuery.data.contested_taste.lean_ratio.toFixed(2),
                  unit:
                    obscurityQuery.data.contested_taste.lean_ratio === null
                      ? 'NO LEAN TO TAKE'
                      : obscurityQuery.data.contested_taste.lean_ratio > 1.2
                        ? 'THEY SEEK OUT THE ARGUMENTS'
                        : obscurityQuery.data.contested_taste.lean_ratio < 0.8
                          ? 'THEY STAY WHERE PEOPLE AGREE'
                          : 'NO STRONG LEAN',
                },
              ]
            : undefined
        }
        caveat={
          obscurityQuery.data?.contested_taste
            ? `Read over ${obscurityQuery.data.contested_taste.measured_films.toLocaleString()} films with a readable histogram. Contested means the crowd's own histogram is in the top decile of spread; agreed means the bottom. ${
                obscurityQuery.data.contested_taste.lean_ratio === null
                  ? 'With no agreed-on films to divide by, the lean is left blank rather than reported as infinite.'
                  : 'The lean is contested films divided by agreed ones.'
              }`
            : undefined
        }
      >
        {panelState({
          isLoading: obscurityQuery.isLoading,
          error: obscurityQuery.error,
          isEmpty: (obscurityQuery.data?.contested_taste?.most_contested.length ?? 0) === 0,
          onRetry: () => obscurityQuery.refetch(),
          errorTitle: 'Contested taste could not be computed',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'No histogram imported yet',
            body: "Spread is read from Letterboxd's own per-film rating histogram. Until that backfill reaches this library there is no crowd to be divided.",
          },
        }) ?? (
          <Posters
            items={(obscurityQuery.data?.contested_taste?.most_contested ?? [])
              .slice(0, 6)
              .map((film) => ({
                title: film.year ? `${film.title} (${film.year})` : film.title,
                posterUrl: film.poster_url,
                href: film.letterboxd_url ?? undefined,
                sub: `${film.rating_count?.toLocaleString() ?? '—'} ratings on Letterboxd`,
                right: film.profile_rating.toFixed(1),
                tone: 'var(--accent)',
                rightCaption: 'their star',
              }))}
          />
        )}
      </Panel>

      <Panel
        title="FILMOGRAPHY RUNS"
        src="movie_enrichments.credits"
        blurb="Stretches where one director keeps reappearing. A run must span more than one date — a single-day cluster is usually an export dating a backlog to its import."
        stats={
          stats?.director_runs.biggest
            ? [
                { big: stats.director_runs.count.toLocaleString(), unit: 'RUNS' },
                {
                  big: stats.director_runs.biggest.films.toLocaleString(),
                  unit: 'LONGEST',
                  tone: 'var(--accent)',
                },
              ]
            : undefined
        }
        caveat={
          stats
            ? `${stats.director_runs.count} stretch${stats.director_runs.count === 1 ? '' : 'es'} of three or more inside a fortnight. Counted over films held, never as a completion score: TMDB's filmography size is not in the film payload, and a denominator would be a guess.`
            : undefined
        }
      >
        {panelState({
          isLoading: statsQuery.isLoading,
          error: statsQuery.error,
          isEmpty: (stats?.director_runs.recent.length ?? 0) === 0,
          onRetry: () => statsQuery.refetch(),
          errorTitle: 'Director runs could not be loaded',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'No run long enough to name',
            body: 'A run needs several films by one director across more than one date, and enough enrichment to know who directed them.',
          },
        }) ?? (
          <Rows
            columns="minmax(0,1fr) 44px 72px 74px minmax(0,1.1fr)"
            head={[
              'DIRECTOR',
              ['FILMS', 'right'],
              ['SPAN', 'right'],
              ['STARTED', 'right'],
              'WHAT',
            ]}
            rows={(stats?.director_runs.recent ?? []).slice(0, 6).map((run) => ({
              cells: [
                cell(run.director, { font: 's', size: '11.5px', tone: 'var(--ink)' }),
                cell(String(run.films), { align: 'right', tone: 'var(--accent)' }),
                cell(`over ${run.days} days`, {
                  align: 'right',
                  size: '10px',
                  tone: 'var(--ink3)',
                }),
                cell(
                  new Date(run.started).toLocaleDateString('en-GB', {
                    month: 'short',
                    year: 'numeric',
                  }),
                  { align: 'right', size: '10px', tone: 'var(--muted)' },
                ),
                cell(run.titles.slice(0, 3).join(', '), {
                  font: 's',
                  size: '10px',
                  tone: 'var(--dim)',
                  wrap: true,
                }),
              ],
            }))}
          />
        )}
      </Panel>

      <Panel
        title="SERIES WORKED THROUGH"
        src="movie_enrichments.collection"
        blurb="Franchises and collections rather than people. A different question from filmography runs, and often answered very differently."
        caveat="A count of films held, not a completion score: TMDB's collection size is not in the film payload, so a denominator would be invented. Singles are excluded — one film is not a franchise."
      >
        {panelState({
          isLoading: statsQuery.isLoading,
          error: statsQuery.error,
          isEmpty: (stats?.franchises.length ?? 0) === 0,
          onRetry: () => statsQuery.refetch(),
          errorTitle: 'Series could not be loaded',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'No series with more than one film',
            body: 'A collection needs at least two films held from it before it is a series rather than a single.',
          },
        }) ?? (
          <Rows
            columns="minmax(0,1fr) 60px 66px"
            head={['SERIES', ['FILMS', 'right'], ['AVG', 'right']]}
            rows={(stats?.franchises ?? []).slice(0, 8).map((series) => ({
              cells: [
                cell(series.name, { font: 's', size: '11.5px', tone: 'var(--ink)' }),
                cell(String(series.films), { align: 'right', tone: 'var(--accent)' }),
                // An unrated series has no average, not an average of zero.
                cell(series.average_rating === null ? '—' : series.average_rating.toFixed(1), {
                  align: 'right',
                  tone: series.average_rating === null ? 'var(--dim)' : 'var(--ink2)',
                }),
              ],
            }))}
          />
        )}
      </Panel>

      <Panel
        title="THE CREW BEYOND THE BIG THREE"
        src="movie_enrichments.credits"
        blurb="Composers, cinematographers, editors, writers and designers — credits TMDB has stored since enrichment began and nothing has read until now."
        caveat="Only the credits TMDB records. A film with no enrichment contributes nobody, which is why these counts run below the library total."
      >
        {panelState({
          isLoading: statsQuery.isLoading,
          error: statsQuery.error,
          isEmpty:
            (stats?.top_composers.length ?? 0) +
              (stats?.top_cinematographers.length ?? 0) +
              (stats?.top_editors.length ?? 0) +
              (stats?.top_writers.length ?? 0) ===
            0,
          onRetry: () => statsQuery.refetch(),
          errorTitle: 'Crew credits could not be loaded',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'No crew credits enriched yet',
            body: 'TMDB enrichment has not reached enough of this library to name anybody behind the camera.',
            cta: { label: 'SEE THE MATCH RATE', href: sectionHref('films', 'gaps') },
          },
        }) ?? (
          <Rows
            columns="96px minmax(0,1fr) 44px"
            head={['ROLE', 'MOST SEEN', ['FILMS', 'right']]}
            rows={(
              [
                ['Composer', stats?.top_composers?.[0]],
                ['Cinematographer', stats?.top_cinematographers?.[0]],
                ['Editor', stats?.top_editors?.[0]],
                ['Writer', stats?.top_writers?.[0]],
                ['Producer', stats?.top_producers?.[0]],
                ['Production design', stats?.top_production_designers?.[0]],
                ['Costume design', stats?.top_costume_designers?.[0]],
                ['Casting', stats?.top_casting?.[0]],
              ] as Array<[string, { name: string; count: number } | undefined]>
            )
              .filter(([, person]) => Boolean(person))
              .map(([role, person]) => ({
                cells: [
                  cell(role, { size: '9.5px', tone: 'var(--muted)' }),
                  cell(person!.name, { font: 's', size: '10.5px', tone: 'var(--ink2)', wrap: true }),
                  cell(String(person!.count), { align: 'right', tone: 'var(--accent)' }),
                ],
              }))}
          />
        )}
      </Panel>

      {/* Only rendered when the import actually reported a limitation. An empty
          "what is missing" heading reads as a fact we failed to fetch, which is
          the opposite of what this panel is for. */}
      {(analysis?.data_coverage?.limitations?.length ?? 0) > 0 ? (
        <Panel
          title="WHAT THIS IMPORT COULD NOT REACH"
          src="profile_syncs.coverage"
          blurb={analysis?.data_coverage?.summary}
          caveat="Stated by the import itself rather than inferred from an empty panel. A surface listed here is one nothing on this tab can be computed from."
        >
          <Notes
            items={(analysis?.data_coverage?.limitations ?? []).map((limitation) => ({
              label: 'Coverage note',
              text: limitation,
            }))}
          />
        </Panel>
      ) : null}

      <Panel title="WHAT WE ADD, AND WHAT WE CANNOT SEE" src="the honest footer" wide>
        <Notes
          items={[
            {
              label: 'Letterboxd already shows them their own stats',
              text: (
                <>
                  Genres, decades, countries and a rating histogram are on their own stats page, and
                  we link straight to it rather than pretending we computed it first —{' '}
                  <a
                    href={`https://letterboxd.com/${subject}/stats/`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    letterboxd.com/{subject}/stats
                  </a>
                  .
                </>
              ),
            },
            {
              label: 'What only we can show',
              text: 'Everything that needs a second profile or a second read: overlaps, drift, unfollows, rating changes, and every panel in Overlaps.',
            },
            {
              label: 'What we still cannot see',
              text: 'When a rating was given, what time of day anything was watched, and anything private. Pronouns, comments, likes and deleted history need an owner export.',
            },
            {
              label: 'Where the gaps are listed',
              text: (
                <Link href={sectionHref('data', 'missing')}>
                  Data › What&rsquo;s missing names every panel that is waiting on something, and
                  who it is waiting on.
                </Link>
              ),
            },
          ]}
        />
      </Panel>
    </>
  );
}
