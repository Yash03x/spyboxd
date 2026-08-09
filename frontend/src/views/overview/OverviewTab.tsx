'use client';

import React from 'react';
import { useQuery } from '@tanstack/react-query';

import Panel from '../../components/terminal/Panel';
import Bars from '../../components/terminal/bodies/Bars';
import Rows, { cell } from '../../components/terminal/bodies/Rows';
import Spark from '../../components/terminal/bodies/Spark';
import { CoWatchMatrix } from '../../components/terminal/bodies/Matrix';
import { BarsSkeleton, PanelSkeleton, panelState } from '../../components/terminal/states';
import { sectionHref } from '../../components/terminal/sections';
import { formatDay } from '../../components/terminal/dates';
import { count } from '../../components/terminal/plural';
import { importState, sinceLabel } from '../../components/terminal/profileState';
import { MIN_RATED_OVERLAP, withRatedEvidence } from '../../components/terminal/pairEvidence';
import { useAdminScope } from '../../hooks/useAdminScope';
import { useScopedProfiles } from '../../hooks/useScopedProfiles';
import {
  activityApi,
  changesApi,
  dashboardApi,
  type GroupSignalPair,
  type ProfileInfo,
  type RecentChange,
} from '../../services/api';

const RATING_ORDER = ['5.0', '4.5', '4.0', '3.5', '3.0', '2.5', '2.0', '1.5', '1.0', '0.5'];

const STAR_LABEL: Record<string, string> = {
  '5.0': '★★★★★',
  '4.5': '★★★★½',
  '4.0': '★★★★',
  '3.5': '★★★½',
  '3.0': '★★★',
  '2.5': '★★½',
  '2.0': '★★',
  '1.5': '★½',
  '1.0': '★',
  '0.5': '½',
};

const MONTH_INITIAL = ['J', 'F', 'M', 'A', 'M', 'J', 'J', 'A', 'S', 'O', 'N', 'D'];

function relativeDays(iso: string | null | undefined): string {
  if (!iso) return 'never';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return 'never';
  const hours = Math.round((Date.now() - then) / 36e5);
  if (hours < 1) return 'just now';
  if (hours < 48) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

/** Plain-English summary of one detected change, plus where it is explained. */
function describeChange(change: RecentChange): { what: string; where: string; href: string } {
  const film = change.movie?.title ?? change.list?.name ?? change.entity_type;
  // Every arm below is a change type `record_profile_changes` actually
  // writes. Two of the original arms -- `watch_added` and `rating_added` --
  // were names nothing in the backend has ever emitted, so the everyday
  // events (`diary_added`, `film_added`) fell through to the default and a
  // newly logged film was captioned "diary added" and pointed at Data ›
  // What's missing, a tab about scrape gaps.
  switch (change.change_type) {
    case 'diary_added':
      return { what: `${film} logged`, where: 'Overlaps › Together', href: sectionHref('overlaps', 'together') };
    case 'diary_removed':
      return { what: `${film} — diary entry gone`, where: 'Data › Lost & found', href: sectionHref('data', 'lost') };
    case 'film_added':
      return { what: `${film} first seen`, where: 'Films › The library', href: sectionHref('films', 'library') };
    case 'film_removed':
      return { what: `${film} no longer listed`, where: 'Data › Lost & found', href: sectionHref('data', 'lost') };
    case 'rating_changed':
      return {
        what: `${film} — rating changed`,
        where: 'People › One person',
        href: sectionHref('people', 'one'),
      };
    case 'like_changed':
      return { what: `${film} — like changed`, where: 'People › One person', href: sectionHref('people', 'one') };
    case 'review_added':
      return { what: `${film} reviewed`, where: 'People › Reach', href: sectionHref('people', 'reach') };
    case 'review_updated':
    case 'text_changed':
      return { what: `${film} — review rewritten`, where: 'People › Reach', href: sectionHref('people', 'reach') };
    case 'review_removed':
      return { what: `${film} — review gone`, where: 'Data › Lost & found', href: sectionHref('data', 'lost') };
    case 'watchlist_added':
      return { what: `${film} queued`, where: 'Tonight › Picks', href: sectionHref('tonight', 'picks') };
    case 'watchlist_removed':
      return { what: `${film} left the watchlist`, where: 'Tonight › Picks', href: sectionHref('tonight', 'picks') };
    case 'favorite_added':
      return { what: `${film} made a favourite`, where: 'People › One person', href: sectionHref('people', 'one') };
    case 'favorite_removed':
      return { what: `${film} dropped as a favourite`, where: 'People › One person', href: sectionHref('people', 'one') };
    case 'follow_added':
    case 'follower_gained':
      return { what: `${film || 'A follow'} added`, where: 'People › The circle', href: sectionHref('people', 'circle') };
    case 'follow_removed':
    case 'follower_lost':
      return { what: `${film || 'A follow'} dropped`, where: 'People › The circle', href: sectionHref('people', 'circle') };
    case 'list_added':
    case 'list_updated':
    case 'list_removed':
    case 'list_item_added':
    case 'list_item_removed':
    case 'list_item_updated':
      return { what: `List "${film}" changed`, where: 'Tonight › Lists', href: sectionHref('tonight', 'lists') };
    default:
      return {
        what: `${film} — ${change.change_type.replace(/_/g, ' ')}`,
        where: 'Data › What’s missing',
        href: sectionHref('data', 'missing'),
      };
  }
}

/** Build the co-watch matrix from the pairs the group-signals endpoint returns. */
function matrixFromPairs(usernames: string[], pairs: GroupSignalPair[]) {
  const size = usernames.length;
  const index = new Map(usernames.map((name, position) => [name.toLowerCase(), position]));
  const overlaps: number[][] = Array.from({ length: size }, () => Array(size).fill(0));
  const gaps: (number | null)[][] = Array.from({ length: size }, () => Array(size).fill(null));

  pairs.forEach((pair) => {
    const [left, right] = pair.profiles;
    const i = index.get((left ?? '').toLowerCase());
    const j = index.get((right ?? '').toLowerCase());
    if (i === undefined || j === undefined) return;
    overlaps[i][j] = pair.shared_titles;
    overlaps[j][i] = pair.shared_titles;
    // A gap over fewer shared ratings than the evidence floor renders as the
    // same dash as "no comparable ratings" — a 0.00 built on one rating is a
    // coincidence wearing a measurement's clothes, and the caveat already
    // tells the reader what the dash means.
    const measurable = pair.rating_overlap_count >= MIN_RATED_OVERLAP;
    gaps[i][j] = measurable ? pair.average_rating_gap : null;
    gaps[j][i] = measurable ? pair.average_rating_gap : null;
  });

  return { overlaps, gaps };
}

export default function OverviewTab() {
  const { effectiveScope, userReady } = useAdminScope();
  const profilesQuery = useScopedProfiles();
  const profiles = React.useMemo(() => profilesQuery.data ?? [], [profilesQuery.data]);
  const usernames = React.useMemo(() => profiles.map((profile) => profile.username), [profiles]);

  const analyticsQuery = useQuery({
    queryKey: ['dashboard-analytics', effectiveScope],
    queryFn: () => dashboardApi.getAnalytics(effectiveScope),
    enabled: userReady,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const changesQuery = useQuery({
    queryKey: ['recent-changes', usernames],
    queryFn: () => changesApi.getRecentChanges({ profiles: usernames, limit: 8 }),
    enabled: userReady && usernames.length > 0,
    staleTime: 60 * 1000,
    refetchOnWindowFocus: false,
  });

  // The window the panel actually drew from, so the caveat states it rather
  // than the copy implying one.
  const oldestChangeAt = changesQuery.data?.changes.at(-1)?.detected_at ?? null;

  const marathonsQuery = useQuery({
    queryKey: ['activity-marathons', usernames],
    queryFn: () => activityApi.getMarathons(usernames, 6),
    enabled: userReady && usernames.length > 0,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const stats = analyticsQuery.data?.system_stats;
  const activity = analyticsQuery.data?.activity_data ?? [];
  const distribution = analyticsQuery.data?.rating_distribution ?? {};
  const pairs = analyticsQuery.data?.group_signals.aligned_pairs ?? [];

  // ---- 01 · the group in five numbers -------------------------------------
  const groupStats = stats
    ? [
        // From the same snapshot as the other four. Reading the separate
        // profiles query here put a confident 0 beside real film and
        // rating totals whenever that slower query was still in flight or
        // had failed -- and counted pending profiles the other four
        // numbers exclude, so the row mixed denominators unlabelled.
        { big: stats.total_profiles.toLocaleString(), unit: 'PROFILES', tone: 'var(--accent)' },
        { big: stats.total_movies_tracked.toLocaleString(), unit: 'FILMS' },
        {
          big: Object.values(distribution).reduce((sum, value) => sum + value, 0).toLocaleString(),
          unit: 'RATINGS',
        },
        { big: stats.total_reviews.toLocaleString(), unit: 'REVIEWS' },
        { big: stats.global_avg_rating ? stats.global_avg_rating.toFixed(2) : '—', unit: 'GROUP AVG' },
      ]
    : undefined;

  // ---- 05 · this year, month by month -------------------------------------
  const sparkItems = activity.map((entry) => {
    const month = Number(entry.month?.slice(5, 7) ?? '1') - 1;
    return {
      label: MONTH_INITIAL[Number.isNaN(month) ? 0 : month] ?? '?',
      value: entry.movies_watched,
      inner: entry.unique_movies ?? undefined,
      display: entry.movies_watched === 0 ? '—' : String(entry.movies_watched),
      // The month in progress is drawn hatched, as it is everywhere else that
      // renders this feed. Solid, five days of August stood next to twelve
      // full months and read as the group's watching collapsing.
      partial: entry.is_partial,
      hint: `${entry.month}${entry.is_partial ? ', month to date' : ''}: ${count(entry.movies_watched, 'watch', 'watches')}`,
    };
  });

  // ---- 06 · how the group rates -------------------------------------------
  const ratingTotal = Object.values(distribution).reduce((sum, value) => sum + value, 0);
  const ratingBars = RATING_ORDER.filter((key) => key in distribution).map((key) => ({
    name: STAR_LABEL[key] ?? key,
    weight: distribution[key],
    value: distribution[key].toLocaleString(),
    sub: ratingTotal ? `${Math.round((distribution[key] / ratingTotal) * 100)}%` : '',
  }));

  // Completed profiles only: the aggregates beside this grid are computed
  // over completed imports, and a row for a profile whose scrape has not
  // finished can only ever render the dash that means "no shared film" — an
  // unread profile is not one that shares nothing.
  const matrixUsernames = profiles
    .filter((profile) => profile.scraping_status === 'completed')
    .map((profile) => profile.username);
  const matrix = matrixFromPairs(matrixUsernames, pairs);
  // Ranked among pairs with enough shared ratings to mean something. Sorted
  // raw, this crown was won by a 0.00 gap resting on three shared ratings —
  // the runner-up had one — while the caveat attributed the agreement to the
  // pair's 89 shared films.
  const closest = withRatedEvidence(pairs).sort(
    (a, b) => (a.average_rating_gap ?? 9) - (b.average_rating_gap ?? 9),
  )[0];

  return (
    <>
      <Panel
        title="THE GROUP, IN FIVE NUMBERS"
        src="rollups · profiles · movies"
        stats={groupStats}
        caveat="Totals across everything imported, not this month. The store is append-only, so these only ever go up — a number falling means a bug, not a deletion."
      >
        {panelState({
          isLoading: analyticsQuery.isLoading,
          error: analyticsQuery.error,
          onRetry: () => analyticsQuery.refetch(),
          errorTitle: 'Group totals could not be loaded',
          errorBody: 'The aggregate endpoint did not answer. Every other panel on this tab is unaffected.',
          skeleton: <PanelSkeleton rows={2} height={21} />,
        })}
      </Panel>

      {/* Titled "since the last refresh" while asking for the whole change
          history, which the API distinguishes and reports back in `scope`.
          The section's question is "what happened while I was away", and a
          reader who was away a fortnight is not served by one sync's worth of
          rows -- so the query stays and the copy stops claiming otherwise.
          The caveat prints the window it actually drew from. */}
      <Panel
        title="THE LATEST CHANGES WE DETECTED"
        src="profile_data_changes · detected_at"
        blurb="The most recent changes across the selection, newest first — not one sync's worth. A profile that was not due yet has nothing here, which is not the same as nothing having happened."
        caveat={
          oldestChangeAt
            ? `The ${count(changesQuery.data?.changes.length ?? 0, 'most recent change')}, reaching back to ${formatDay(oldestChangeAt)}. Change needs two authoritative reads: a profile's first import is a baseline and deliberately emits nothing.`
            : "Change needs two authoritative reads. A profile's first import is a baseline and deliberately emits nothing."
        }
      >
        {panelState({
          isLoading: changesQuery.isLoading,
          error: changesQuery.error,
          isEmpty: (changesQuery.data?.changes.length ?? 0) === 0,
          severity: 'quiet',
          errorTitle: 'Change history unavailable',
          errorBody: 'The rest of the tab is unaffected; this strip retries on demand.',
          onRetry: () => changesQuery.refetch(),
          empty: {
            title: 'No change detected yet',
            body: 'Every tracked surface has come back identical to the read before it. New rows appear here the moment a refresh finds one.',
            cta: { label: 'OPEN REFRESH LEDGER', href: sectionHref('data', 'refreshes') },
          },
        }) ?? (
          <Rows
            columns="minmax(0,1.6fr) 62px minmax(0,1.4fr)"
            head={['WHAT', ['WHO', 'right'], 'WHERE IT IS EXPLAINED']}
            rows={(changesQuery.data?.changes ?? []).map((change) => {
              const described = describeChange(change);
              return {
                href: described.href,
                cells: [
                  cell(described.what, { font: 's', wrap: true }),
                  cell(`@${change.username}`, { align: 'right', size: '10px', tone: 'var(--muted)' }),
                  cell(described.where, { size: '10px', tone: 'var(--accent)' }),
                ],
              };
            })}
          />
        )}
      </Panel>

      <Panel
        title="WHO WATCHES WITH WHOM"
        src="watch_events pairs"
        wide
        blurb="Above the diagonal: films both have seen. Below it: how far apart their stars land on those same films. One grid answers both questions people actually ask."
        caveat={
          closest
            ? `${closest.profiles.join(' and ')} are the closest pair here: agreeing within ${(closest.average_rating_gap ?? 0).toFixed(2)} of a star across ${closest.rating_overlap_count.toLocaleString()} shared ratings, on ${closest.shared_titles.toLocaleString()} shared films. Every pair in the selection is drawn — a dash above the diagonal is a pair with no shared film, and below it a pair with fewer than ${MIN_RATED_OVERLAP} shared ratings, which is too few to call a distance.`
            : `No pair shares ${MIN_RATED_OVERLAP} rated films yet, so nobody is called closest on this grid.`
        }
      >
        {panelState({
          isLoading: analyticsQuery.isLoading || profilesQuery.isLoading,
          error: analyticsQuery.error,
          isEmpty: usernames.length < 2 || pairs.length === 0,
          onRetry: () => analyticsQuery.refetch(),
          errorTitle: 'The co-watch grid could not be built',
          errorBody: 'Pair overlap comes from the group-signals aggregate, which did not answer.',
          empty: {
            title: 'Two profiles are needed',
            body: 'Overlap and star distance are both pair measures. Monitor a second profile and this grid fills in on the next load.',
            cta: { label: 'CHOOSE WHO TO MONITOR', href: sectionHref('data', 'profiles') },
          },
        }) ?? (
          <CoWatchMatrix labels={matrixUsernames} overlaps={matrix.overlaps} gaps={matrix.gaps} />
        )}
      </Panel>

      <Panel
        title="EVERYONE WE ARE WATCHING"
        src="profiles · refresh_runs"
        caveat="SINCE is the earliest diary entry we hold, not a join date — Letterboxd publishes no join date on a public page, and guessing one would be the easiest lie in the product. Stop watching somebody and their history stays: the store is append-only, so untracking hides a profile without deleting anything."
      >
        {panelState({
          isLoading: profilesQuery.isLoading,
          error: profilesQuery.error,
          isEmpty: profiles.length === 0,
          onRetry: () => profilesQuery.refetch(),
          errorTitle: 'Failed to load your profiles',
          errorBody: 'Your monitored set could not be read, so nothing on this tab can be scoped to it.',
          severity: 'fatal',
          empty: {
            title: 'Choose your first monitored profile',
            body: 'Pick an existing Letterboxd profile, or ask for a username. This section only ever uses the profiles you monitor.',
            cta: { label: 'CHOOSE OR REQUEST A PROFILE', href: sectionHref('data', 'profiles') },
          },
        }) ?? (
          <Rows
            columns="minmax(0,1.1fr) 54px 66px 62px minmax(0,1fr)"
            head={[
              'PROFILE',
              ['FILMS', 'right'],
              ['SINCE', 'right'],
              ['LAST SYNC', 'right'],
              'STATE',
            ]}
            rows={profiles.map((profile) => {
              const state = importState(profile);
              const since = sinceLabel(profile);
              return {
                cells: [
                  cell(`@${profile.username}`),
                  cell((profile.total_films ?? 0).toLocaleString(), {
                    align: 'right',
                    tone: 'var(--ink)',
                  }),
                  cell(since.label, {
                    align: 'right',
                    size: '10px',
                    tone: since.tone,
                  }),
                  cell(relativeDays(profile.last_scraped_at), {
                    align: 'right',
                    size: '10px',
                    tone: 'var(--muted)',
                  }),
                  cell(state.label, { size: '10px', tone: state.tone, font: 's', wrap: true }),
                ],
              };
            })}
          />
        )}
      </Panel>

      <Panel
        title="THE LAST TWELVE MONTHS"
        src="watch_events.watched_date"
        blurb="Full bar is watches. The lighter block inside it is how many were films nobody in the group had logged before — the gap between the two is rewatching and catching up."
        caveat="A month with no bar had no dated entry at all. The window ends with the month in progress, drawn hatched because it is not finished, not a collapse in watching."
      >
        {panelState({
          isLoading: analyticsQuery.isLoading,
          error: analyticsQuery.error,
          isEmpty: sparkItems.length === 0,
          onRetry: () => analyticsQuery.refetch(),
          errorTitle: 'No activity data available',
          errorBody: 'The monthly aggregate did not answer.',
          empty: {
            title: 'No dated watches this year',
            body: 'No dated watch events fall inside the charted window. Undated entries are excluded rather than placed on a guessed month.',
          },
        }) ?? <Spark items={sparkItems} />}
      </Panel>

      <Panel
        title="HOW THE GROUP RATES"
        src="ratings.rating"
        blurb="The whole distribution, not an average. Where a group almost never uses the bottom of the scale, that is worth knowing before reading any gap figure elsewhere."
      >
        {panelState({
          isLoading: analyticsQuery.isLoading,
          error: analyticsQuery.error,
          isEmpty: ratingBars.length === 0,
          onRetry: () => analyticsQuery.refetch(),
          errorTitle: 'The rating distribution could not be loaded',
          errorBody: 'The aggregate endpoint did not answer.',
          empty: {
            title: 'No ratings imported yet',
            body: 'A profile has to have rated something before a distribution exists.',
          },
          skeleton: <BarsSkeleton rows={10} />,
        }) ?? <Bars items={ratingBars} />}
      </Panel>

      <Panel
        title="MARATHON DAYS"
        src="watch_events grouped by date"
        blurb="Three or more films logged by one person in a day. Rare enough to be interesting, common enough to have a pattern."
        caveat={marathonsQuery.data?.caveat}
      >
        {panelState({
          isLoading: marathonsQuery.isLoading,
          error: marathonsQuery.error,
          isEmpty: (marathonsQuery.data?.marathons.length ?? 0) === 0,
          onRetry: () => marathonsQuery.refetch(),
          errorTitle: 'Marathon days could not be loaded',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'No marathon days yet',
            body: 'Nobody in the selection has three or more dated films on one day. Undated entries cannot be grouped into a day at all.',
          },
        }) ?? (
          <Rows
            columns="68px minmax(0,1fr) 30px"
            head={['DATE', 'WHO · WHAT', ['N', 'right']]}
            rows={(marathonsQuery.data?.marathons ?? []).map((day) => ({
              cells: [
                cell(
                  // Local, not UTC: `new Date('2026-07-15')` is UTC midnight,
                  // which prints as the 14th anywhere west of Greenwich.
                  formatDay(day.date),
                  { size: '10.5px', tone: 'var(--ink3)' },
                ),
                cell(`@${day.username} · ${day.titles.slice(0, 3).join(', ')}`, {
                  font: 's',
                  size: '10.5px',
                  wrap: true,
                }),
                cell(String(day.films), { align: 'right', tone: 'var(--accent)' }),
              ],
            }))}
          />
        )}
      </Panel>

      <Panel
        title="LEAVING SOON"
        src="movie_watch_providers.fetched_at"
        blurb="Where a film can be streamed right now, and how recently we checked."
      >
        {/* Deliberately not a countdown. TMDB publishes which services carry a
            film today, never the date it leaves one, so a "4 days left" figure
            would be invented rather than read. The panel says what it is
            waiting for instead of showing a number it cannot stand behind. */}
        <div className="px-[10px] py-[14px]">
          <p className="m-0 font-term-sans text-t115 font-semibold text-term-ink">
            Can&rsquo;t answer this yet
          </p>
          <p className="m-0 mt-[5px] max-w-[42rem] font-term-sans text-t105 text-term-ink3">
            A countdown needs an expiry date. The provider feed publishes which services carry a film
            today and nothing about when that stops being true, so every &ldquo;days left&rdquo; figure
            would be a guess wearing a number&rsquo;s clothes. Two consecutive reads of the same region
            would let us infer a departure after the fact; until that history exists, availability is
            shown in Tonight with its read date attached and no deadline claimed.
          </p>
        </div>
      </Panel>
    </>
  );
}
