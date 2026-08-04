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
                { big: summary.one_day_gap_events.toLocaleString(), unit: 'WITHIN A DAY' },
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
          empty: emptyState,
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
          empty: emptyState,
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
    </>
  );
}
