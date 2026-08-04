'use client';

import React from 'react';
import { useQuery } from '@tanstack/react-query';

import Panel from '../../components/terminal/Panel';
import { formatDay } from '../../components/terminal/dates';
import Bars from '../../components/terminal/bodies/Bars';
import Posters from '../../components/terminal/bodies/Posters';
import { BarsSkeleton, panelState } from '../../components/terminal/states';
import { sectionHref } from '../../components/terminal/sections';
import {
  firstWatchApi,
  spySignalsApi,
  type CoWatchFollowGraphSummary,
  type RewatchEcho,
} from '../../services/api';

/**
 * Why an echo is more than a coincidence, in the honest order: a follow edge
 * observed at the time is evidence; its absence is not evidence of the
 * opposite, and an unobservable follow graph is neither.
 */
function echoReason(echo: RewatchEcho): { text: string; tone: string } {
  if (echo.follow_backed) {
    return { text: 'followed the earlier watcher', tone: 'var(--ok)' };
  }
  if (echo.follow_backed === false) {
    return { text: 'no follow between them', tone: 'var(--ink3)' };
  }
  return { text: 'follows not imported', tone: 'var(--dim)' };
}

function echoTiming(echo: RewatchEcho): string {
  if (echo.timing === 'same_day') return 'Same day';
  return `${echo.day_gap} day${echo.day_gap === 1 ? '' : 's'} later`;
}

/**
 * Gap echoes split three ways: the later watcher followed the earlier one,
 * they demonstrably did not, or no authoritative follow import covers the
 * pair. All three are stated. Reporting only the first leaves the reader to
 * subtract, and subtraction cannot distinguish "we checked and found nothing"
 * from "we could not check" — which are opposite facts.
 */
function followCaveat(graph: CoWatchFollowGraphSummary | undefined): string {
  if (!graph) {
    return 'Where a follow edge could not be read, the row says so rather than implying there was none.';
  }

  const parts = [
    `A follow marker appears on ${graph.follow_backed_gap_events} of the ${graph.gap_events} echoes with a gap.`,
    `${graph.coincidental_gap_events} were checked and carry no follow in either direction.`,
    `${graph.undetermined_gap_events} stay undetermined.`,
    // The reason they stay that way is computed server-side from real coverage
    // and passed through verbatim. Re-deriving it here would let the sentence
    // and the number it explains drift apart.
    ...graph.warnings,
  ];
  return parts.join(' ');
}

export default function EchoesTab({ profiles, gapDays }: { profiles: string[]; gapDays: number }) {
  // Echoes need a wider window than a co-watch: somebody acting on a
  // recommendation takes a fortnight, not a day.
  const echoWindow = Math.max(gapDays, 14);

  const echoesQuery = useQuery({
    queryKey: ['rewatch-echoes', profiles, echoWindow],
    queryFn: () => spySignalsApi.getRewatchEchoes(profiles, echoWindow),
    enabled: profiles.length >= 2,
    staleTime: 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const orderQuery = useQuery({
    queryKey: ['first-watch-order', profiles],
    queryFn: () => firstWatchApi.getOrder(profiles),
    enabled: profiles.length >= 2,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const firstsQuery = useQuery({
    queryKey: ['shared-firsts', profiles],
    queryFn: () => firstWatchApi.getSharedFirsts(profiles, 10),
    enabled: profiles.length >= 2,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const echoes = echoesQuery.data?.echoes ?? [];
  const summary = echoesQuery.data?.summary;
  const graph = echoesQuery.data?.follow_graph;

  const twoProfilesNeeded = {
    title: 'Two profiles are needed',
    body: 'An echo is one person revisiting something soon after somebody else did. There is no echo in a single history.',
    cta: { label: 'CHOOSE WHO TO MONITOR', href: sectionHref('data', 'profiles') },
  };

  return (
    <>
      <Panel
        title="WATCHED IT AGAIN, SO DID THEY"
        src="profile_films.watch_count"
        blurb={`One person rewatched something, and inside ${echoWindow} days somebody else did too. The closest thing in the data to a recommendation being taken.`}
        stats={
          summary
            ? [
                { big: summary.echoes.toLocaleString(), unit: 'ECHOES', tone: 'var(--accent)' },
                { big: summary.same_day.toLocaleString(), unit: 'SAME DAY' },
                { big: summary.movies.toLocaleString(), unit: 'FILMS' },
              ]
            : undefined
        }
        caveat={followCaveat(graph)}
      >
        {panelState({
          isLoading: echoesQuery.isLoading,
          error: echoesQuery.error,
          isEmpty: profiles.length < 2 || echoes.length === 0,
          severity: 'degraded',
          errorTitle: 'Echoes are unavailable',
          errorBody:
            'Overlaps still work. This panel needs occurrence-level rewatch history for the selected profiles.',
          onRetry: () => echoesQuery.refetch(),
          empty:
            profiles.length < 2
              ? twoProfilesNeeded
              : {
                  title: 'No echoes in this window',
                  body: 'Nobody rewatched a film another selected profile had just revisited. Try a wider closeness or another selection.',
                },
        }) ?? (
          <Posters
            items={echoes.slice(0, 10).map((echo) => {
              const reason = echoReason(echo);
              const leader = echo.participants.find((person) => person.timing_role !== 'follower');
              const follower = echo.participants.find((person) => person.timing_role === 'follower');
              return {
                title: echo.movie.year ? `${echo.movie.title} (${echo.movie.year})` : echo.movie.title,
                posterUrl: echo.movie.poster_url,
                sub: follower
                  ? `@${leader?.username ?? '?'} rewatched, @${follower.username} followed`
                  : echo.participants.map((person) => `@${person.username}`).join(' + '),
                right: echoTiming(echo),
                tone: echo.timing === 'same_day' ? 'var(--ok)' : 'var(--accent)',
                rightCaption: reason.text,
              };
            })}
          />
        )}
      </Panel>

      <Panel
        title="WHO GETS THERE FIRST"
        src="profile_films.first_watched_date"
        blurb="Share of shared films where this person was the earlier watch. High is not better — it means the rest of the group tends to arrive after them."
        caveat={orderQuery.data?.caveat}
      >
        {panelState({
          isLoading: orderQuery.isLoading,
          error: orderQuery.error,
          isEmpty: (orderQuery.data?.profiles ?? []).every((entry) => entry.comparable === 0),
          onRetry: () => orderQuery.refetch(),
          errorTitle: 'First-watch order could not be computed',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'No comparable first watches',
            body: 'No shared film in this selection carries a first-watch date on both sides. Undated entries are excluded rather than assumed late.',
          },
          skeleton: <BarsSkeleton rows={5} />,
        }) ?? (
          <Bars
            items={(orderQuery.data?.profiles ?? []).map((entry) => ({
              name: `@${entry.username}`,
              weight: entry.share ?? 0,
              value: entry.share === null ? '—' : `${Math.round(entry.share * 100)}%`,
              sub: `${entry.firsts} first`,
            }))}
            max={1}
          />
        )}
      </Panel>

      <Panel
        title="SHARED FIRSTS"
        isNew
        src="profile_films.first_watched_date"
        blurb="Same film, same day, and it was the first ever watch for both of them. Stronger than any repeat co-watch, because nobody was catching up with anybody."
        caveat={firstsQuery.data?.caveat}
      >
        {panelState({
          isLoading: firstsQuery.isLoading,
          error: firstsQuery.error,
          isEmpty: (firstsQuery.data?.shared_firsts.length ?? 0) === 0,
          onRetry: () => firstsQuery.refetch(),
          errorTitle: 'Shared firsts could not be loaded',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'No shared firsts yet',
            body: 'This needs a first-watch date on both sides of the same film on the same day. Profiles imported from a ratings snapshot rarely carry one.',
            cta: { label: 'SEE WHAT EACH VIEW NEEDS', href: sectionHref('data', 'missing') },
          },
        }) ?? (
          <Posters
            items={(firstsQuery.data?.shared_firsts ?? []).map((entry) => ({
              title: entry.year ? `${entry.title} (${entry.year})` : entry.title,
              posterUrl: entry.poster_url,
              sub: entry.usernames.map((name) => `@${name}`).join(' + '),
              right: formatDay(entry.date),
              tone: 'var(--ok)',
              rightCaption: 'both first',
            }))}
          />
        )}
      </Panel>
    </>
  );
}
