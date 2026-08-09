'use client';

import React from 'react';
import { useQuery } from '@tanstack/react-query';

import Panel from '../../components/terminal/Panel';
import Bars from '../../components/terminal/bodies/Bars';
import Posters from '../../components/terminal/bodies/Posters';
import Rows, { cell } from '../../components/terminal/bodies/Rows';
import { BarsSkeleton, panelState } from '../../components/terminal/states';
import { sectionHref } from '../../components/terminal/sections';
import { MIN_RATED_OVERLAP, withRatedEvidence } from '../../components/terminal/pairEvidence';
import { count } from '../../components/terminal/plural';
import { spySignalsApi, type GroupSignalEvent, type GroupSignalPair } from '../../services/api';

/** Was "gap days". The tier a co-watch falls into, said the way a person would. */
export function closenessLabel(dayGap: number | null | undefined): { label: string; tone: string } {
  if (dayGap === 0) return { label: 'Same day', tone: 'var(--ok)' };
  if (dayGap === 1) return { label: 'Within a day', tone: 'var(--accent)' };
  if (dayGap !== null && dayGap !== undefined && dayGap <= 3) {
    return { label: 'Within three', tone: 'var(--ink3)' };
  }
  return { label: `Within ${dayGap ?? '?'} days`, tone: 'var(--ink3)' };
}

function eventGap(event: GroupSignalEvent): number | null {
  if (typeof event.day_gap === 'number') return event.day_gap;
  const start = new Date(event.start_date).getTime();
  const end = new Date(event.end_date).getTime();
  if (Number.isNaN(start) || Number.isNaN(end)) return null;
  return Math.round((end - start) / 86400000);
}

function allEvents(
  signals:
    | { same_day_events: GroupSignalEvent[]; one_day_gap_events: GroupSignalEvent[]; gap_events?: GroupSignalEvent[] }
    | undefined,
): GroupSignalEvent[] {
  if (!signals) return [];
  const merged = [
    ...signals.same_day_events,
    ...signals.one_day_gap_events,
    ...(signals.gap_events ?? []),
  ];
  // The three feeds overlap: a same-day event also appears in the wider
  // windows. Dedupe on title plus the window it spans.
  const seen = new Set<string>();
  return merged.filter((event) => {
    const key = `${event.title}|${event.start_date}|${event.profiles.join(',')}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export default function TogetherTab({
  profiles,
  gapDays,
}: {
  profiles: string[];
  gapDays: number;
}) {
  const signalsQuery = useQuery({
    queryKey: ['spy-signals', profiles, gapDays],
    queryFn: () => spySignalsApi.getSignals(profiles, gapDays),
    enabled: profiles.length >= 2,
    staleTime: 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const signals = signalsQuery.data?.group_signals;
  const summary = signals?.summary;
  const events = allEvents(signals).sort(
    (a, b) => new Date(b.start_date).getTime() - new Date(a.start_date).getTime(),
  );
  const pairs: GroupSignalPair[] = signals?.aligned_pairs ?? [];

  // Only pairs whose gap rests on the evidence floor. This list once came
  // back pre-trimmed to the six alignment-scored pairs, which are already
  // evidence-weighted; now that every pair arrives, a raw sort would crown a
  // 0.00 coincidence built on a single shared rating.
  const tightest = withRatedEvidence(pairs).sort(
    (a, b) => (a.average_rating_gap ?? 9) - (b.average_rating_gap ?? 9),
  );

  // Tier counts from the summary, which is computed before the server cuts
  // each event list to 100 rows. Counted from the merged display lists, the
  // "in this window" total could come out SMALLER than its own same-day
  // subset once any tier overflowed the cut — one panel contradicting itself.
  //
  // The summary's gap_events already spans the whole window (day gaps 0
  // through the selection), so it IS the window total; the wider tier bar is
  // the remainder after the two named tiers, never a re-add of them.
  const windowTotal = summary
    ? (summary.gap_events ?? summary.same_day_events + (gapDays >= 1 ? summary.one_day_gap_events : 0))
    : 0;
  const gapRemainder = summary
    ? Math.max(
        0,
        windowTotal - summary.same_day_events - (gapDays >= 1 ? summary.one_day_gap_events : 0),
      )
    : 0;
  const tiers = summary
    ? ([
        { label: 'Same day', count: summary.same_day_events, tone: 'var(--ok)' },
        ...(gapDays >= 1
          ? [{ label: 'Within a day', count: summary.one_day_gap_events, tone: 'var(--accent)' }]
          : []),
        ...(gapDays > 1
          ? [
              {
                label: gapDays <= 3 ? 'Two to three days' : `Two to ${gapDays} days`,
                count: gapRemainder,
                tone: 'var(--ink3)',
              },
            ]
          : []),
      ] as Array<{ label: string; count: number; tone: string }>)
    : [];

  const emptyState = {
    title: 'Two profiles are needed',
    body: 'An overlap is two people watching the same film close together. With one monitored profile there is no second side to compare against.',
    cta: { label: 'CHOOSE WHO TO MONITOR', href: sectionHref('data', 'profiles') },
  };

  /**
   * "Two profiles are needed" is true only when fewer than two are selected.
   * Every panel here used it for any empty result, so two sparse profiles
   * with nothing in common were told to go and monitor somebody — with a
   * button to a page whose job they had already done.
   */
  const nothingFound = (what: string) =>
    profiles.length < 2
      ? emptyState
      : {
          title: `No ${what} in this window`,
          body: 'The selected profiles have nothing that qualifies here. Widen the closeness above, pick a different pair, or wait for the next refresh.',
        };

  return (
    <>
      <Panel
        title="WHAT OVERLAPPED"
        src="watch_events × watch_events"
        blurb="Most recent first. Same film, and both watches land inside the window selected above."
        caveat="Was called the signal feed. An overlap is an observation about timing, never a claim that one watch caused the other."
      >
        {panelState({
          isLoading: signalsQuery.isLoading,
          error: signalsQuery.error,
          isEmpty: profiles.length < 2 || events.length === 0,
          severity: 'fatal',
          errorTitle: 'Overlap scan failed',
          errorBody: 'The selected profiles could not be compared. Check the API connection and try again.',
          onRetry: () => signalsQuery.refetch(),
          empty:
            profiles.length < 2
              ? emptyState
              : {
                  title: 'No overlaps in this window',
                  body: 'Nothing the selected profiles watched lands inside the chosen closeness. Widen it above, or select more profiles.',
                },
        }) ?? (
          <Posters
            items={events.slice(0, 12).map((event) => {
              const gap = eventGap(event);
              const tier = closenessLabel(gap);
              return {
                title: event.year ? `${event.title} (${event.year})` : event.title,
                sub: event.profiles.map((name) => `@${name}`).join(' + '),
                right: tier.label,
                tone: tier.tone,
                rightCaption:
                  event.max_rating_gap !== null
                    ? `★ gap ${event.max_rating_gap.toFixed(1)}`
                    : 'not both rated',
              };
            })}
          />
        )}
      </Panel>

      <Panel
        title="HOW CLOSE IN TIME"
        src="watch_events date deltas"
        stats={
          summary
            ? [
                { big: summary.same_day_events.toLocaleString(), unit: 'SAME DAY', tone: 'var(--ok)' },
                // Only while the window actually includes it. The backend
                // counts one-day gaps regardless of the selected closeness,
                // so under SAME DAY this printed a WITHIN A DAY figure larger
                // than the IN THIS WINDOW total sitting beside it.
                ...(gapDays >= 1
                  ? [{ big: summary.one_day_gap_events.toLocaleString(), unit: 'WITHIN A DAY' }]
                  : []),
                { big: windowTotal.toLocaleString(), unit: 'IN THIS WINDOW' },
              ]
            : undefined
        }
        caveat="Was “gap days: 0 / 1 / 3”. Same day is the only tier strong enough to imply they watched together rather than coincided."
      >
        {panelState({
          isLoading: signalsQuery.isLoading,
          error: signalsQuery.error,
          isEmpty: windowTotal === 0,
          onRetry: () => signalsQuery.refetch(),
          errorTitle: 'Closeness tiers could not be counted',
          errorBody: 'The overlap feed did not answer.',
          empty: nothingFound('overlap close enough to measure'),
          skeleton: <BarsSkeleton rows={3} />,
        }) ?? (
          <Bars
            items={tiers.map((tier) => ({
              name: tier.label,
              weight: tier.count,
              value: tier.count.toLocaleString(),
              sub: windowTotal ? `${Math.round((tier.count / windowTotal) * 100)}%` : '',
              tone: tier.tone,
            }))}
          />
        )}
      </Panel>

      <Panel
        title="CLOSEST PAIR · WIDEST DISAGREEMENT"
        src="ratings × shared films"
        caveat="Agreement is the average distance between their stars on films both have rated. Half a star or less is the threshold worth calling agreement."
      >
        {panelState({
          isLoading: signalsQuery.isLoading,
          error: signalsQuery.error,
          isEmpty: tightest.length === 0,
          onRetry: () => signalsQuery.refetch(),
          errorTitle: 'Pair agreement could not be loaded',
          errorBody: 'The overlap feed did not answer.',
          empty: {
            title: 'Not enough shared ratings yet',
            body: 'Both profiles need a rating on the same film before a star distance can be measured.',
          },
        }) ?? (
          <Rows
            columns="minmax(0,1fr) 92px 62px"
            // The gap is measured over the films both RATED, not everything
            // both watched — printing shared films beside it credited a
            // three-rating coincidence to an 89-film history.
            head={['PAIR', ['★ SHARED', 'right'], ['★ GAP', 'right']]}
            rows={[...tightest.slice(0, 3), ...tightest.slice(-2).reverse()]
              .filter((pair, index, list) => list.findIndex((other) => other === pair) === index)
              .map((pair) => {
                const gap = pair.average_rating_gap ?? 0;
                return {
                  cells: [
                    cell(pair.profiles.map((name) => `@${name}`).join(' + '), { size: '10.5px' }),
                    cell(
                      `${pair.rating_overlap_count.toLocaleString()} of ${pair.shared_titles.toLocaleString()}`,
                      {
                        align: 'right',
                        size: '10px',
                        tone: 'var(--muted)',
                      },
                    ),
                    cell(gap.toFixed(2), {
                      align: 'right',
                      tone: gap <= 0.5 ? 'var(--ok)' : gap >= 0.9 ? 'var(--bad)' : 'var(--ink2)',
                    }),
                  ],
                };
              })}
          />
        )}
      </Panel>

      <Panel
        title="PAIR LEADERBOARD"
        src="overlap counts per pair"
        blurb="Who actually overlaps, ranked. The bar is shared films; the figure beside it is how far apart their stars land on them."
      >
        {panelState({
          isLoading: signalsQuery.isLoading,
          error: signalsQuery.error,
          isEmpty: pairs.length === 0,
          onRetry: () => signalsQuery.refetch(),
          errorTitle: 'The pair leaderboard could not be loaded',
          errorBody: 'The overlap feed did not answer.',
          empty: nothingFound('pair with a shared film'),
          skeleton: <BarsSkeleton rows={6} />,
        }) ?? (
          <Bars
            items={[...pairs]
              .sort((a, b) => b.shared_titles - a.shared_titles)
              .slice(0, 10)
              .map((pair) => ({
                name: pair.profiles.join(' + '),
                weight: pair.shared_titles,
                value: pair.shared_titles.toLocaleString(),
                // Same floor as everywhere a gap is printed: below it the
                // figure is a coincidence, and it renders as the dash the
                // reader already knows means "too thin to measure".
                sub:
                  pair.average_rating_gap !== null &&
                  pair.rating_overlap_count >= MIN_RATED_OVERLAP
                    ? pair.average_rating_gap.toFixed(2)
                    : '—',
              }))}
          />
        )}
      </Panel>

      {/* The three panels below were on v3's dashboard (GroupSignalsPanel) and
          were silently dropped by the redesign handoff despite its "nothing is
          dropped" promise. The endpoint has shipped all three lists the whole
          time. */}
      <Panel
        title="EVERYONE'S SEEN IT"
        src="group_signals.most_shared_titles"
        blurb="The films that travel furthest across the selection — held by the most people, whatever they thought of them."
        caveat="A film needs two holders to appear at all; the count is people, not watches, so a rewatcher counts once."
      >
        {panelState({
          isLoading: signalsQuery.isLoading,
          error: signalsQuery.error,
          isEmpty: (signals?.most_shared_titles.length ?? 0) === 0,
          onRetry: () => signalsQuery.refetch(),
          errorTitle: 'Most shared titles could not be loaded',
          errorBody: 'The overlap feed did not answer.',
          empty: nothingFound('film everybody has seen'),
          skeleton: <BarsSkeleton rows={6} />,
        }) ?? (
          <Bars
            items={(signals?.most_shared_titles ?? []).slice(0, 8).map((movie) => ({
              name: movie.year ? `${movie.title} (${movie.year})` : movie.title,
              weight: movie.profile_count,
              value: count(movie.profile_count, 'person', 'people'),
              sub: movie.average_rating === null ? '—' : movie.average_rating.toFixed(1),
            }))}
          />
        )}
      </Panel>

      <Panel
        title="AGREED ON, AND LIKED"
        src="group_signals.consensus_hits"
        blurb="Shared watches with a strong average and little disagreement. The safest common ground the selection has."
        caveat="Needs two or more ratings on the same film — an average of one opinion is not a consensus. Ranked by average, then by how tightly the stars cluster."
      >
        {panelState({
          isLoading: signalsQuery.isLoading,
          error: signalsQuery.error,
          isEmpty: (signals?.consensus_hits.length ?? 0) === 0,
          onRetry: () => signalsQuery.refetch(),
          errorTitle: 'Consensus hits could not be loaded',
          errorBody: 'The overlap feed did not answer.',
          empty: nothingFound('film the group agreed on'),
        }) ?? (
          <Rows
            columns="minmax(0,1.4fr) 52px 62px 58px"
            head={['FILM', ['AVG', 'right'], ['RATERS', 'right'], ['SPREAD', 'right']]}
            rows={(signals?.consensus_hits ?? []).slice(0, 8).map((movie) => ({
              cells: [
                cell(movie.year ? `${movie.title} (${movie.year})` : movie.title, {
                  font: 's',
                  size: '10.5px',
                  wrap: true,
                }),
                cell(movie.average_rating === null ? '—' : movie.average_rating.toFixed(1), {
                  align: 'right',
                  tone: 'var(--ok)',
                }),
                cell(String(movie.rating_count), { align: 'right', size: '10px', tone: 'var(--muted)' }),
                cell(movie.rating_stddev === null ? '—' : movie.rating_stddev.toFixed(2), {
                  align: 'right',
                  size: '10px',
                  tone: 'var(--muted)',
                }),
              ],
            }))}
          />
        )}
      </Panel>

      <Panel
        title="SPLIT THE ROOM"
        src="group_signals.divisive_titles"
        blurb="Shared watches with the widest spread in stars — the whole selection against itself, not one pair. Head to head holds the pair version."
        caveat="Spread is the standard deviation of the selection's own stars on the film, and it needs two or more raters to exist at all."
      >
        {panelState({
          isLoading: signalsQuery.isLoading,
          error: signalsQuery.error,
          isEmpty: (signals?.divisive_titles.length ?? 0) === 0,
          onRetry: () => signalsQuery.refetch(),
          errorTitle: 'Divisive titles could not be loaded',
          errorBody: 'The overlap feed did not answer.',
          empty: nothingFound('film that split the room'),
        }) ?? (
          <Rows
            columns="minmax(0,1.4fr) 52px 62px 58px"
            head={['FILM', ['AVG', 'right'], ['RATERS', 'right'], ['SPREAD', 'right']]}
            rows={(signals?.divisive_titles ?? []).slice(0, 8).map((movie) => ({
              cells: [
                cell(movie.year ? `${movie.title} (${movie.year})` : movie.title, {
                  font: 's',
                  size: '10.5px',
                  wrap: true,
                }),
                cell(movie.average_rating === null ? '—' : movie.average_rating.toFixed(1), {
                  align: 'right',
                  tone: 'var(--ink2)',
                }),
                cell(String(movie.rating_count), { align: 'right', size: '10px', tone: 'var(--muted)' }),
                cell(movie.rating_stddev === null ? '—' : movie.rating_stddev.toFixed(2), {
                  align: 'right',
                  tone: 'var(--bad)',
                }),
              ],
            }))}
          />
        )}
      </Panel>
    </>
  );
}
