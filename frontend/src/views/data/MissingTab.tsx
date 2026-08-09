'use client';

import React from 'react';
import { useQuery } from '@tanstack/react-query';

import Panel from '../../components/terminal/Panel';
import Rows, { cell } from '../../components/terminal/bodies/Rows';
import { panelState } from '../../components/terminal/states';
import { dataHealthApi, insightsApi, type FeatureReadinessStatus } from '../../services/api';

const READINESS_LABEL: Record<FeatureReadinessStatus, { label: string; tone: string }> = {
  ready: { label: 'Answered in full', tone: 'var(--ok)' },
  partial: { label: 'Partial answer', tone: 'var(--accent)' },
  blocked: { label: "Can't answer yet", tone: 'var(--bad)' },
};

// Was "spy_signals", "pair_dossier", "taste_dna" — schema names in a reader's
// panel. The SRC line is where the schema is allowed to show.
const FEATURE_LABEL: Record<string, string> = {
  spy_signals: 'Overlaps › Together',
  pair_dossier: 'People › Two people',
  signal_calendar: 'Overlaps › When',
  watch_together: 'Tonight › Picks',
  list_mission: 'Tonight › Lists',
  taste_dna: 'People › Taste breakdown',
  rewatch_echoes: 'Overlaps › Echoes',
  taste_timeline: 'People › How taste changed',
  recent_changes: 'Overview › What changed',
};

export default function MissingTab({
  profiles,
  selectionLoading = false,
}: {
  profiles: string[];
  /** The profile list is still on the wire; an empty selection is not
   *  yet a fact, so a disabled query must not report an absence. */
  selectionLoading?: boolean;
}) {
  const enabled = profiles.length > 0;
  const options = { enabled, staleTime: 60 * 1000, refetchOnWindowFocus: false };

  const countsQuery = useQuery({
    queryKey: ['data-counts', profiles],
    queryFn: () => dataHealthApi.getCounts(profiles),
    ...options,
  });
  const privateQuery = useQuery({
    queryKey: ['data-private', profiles],
    queryFn: () => dataHealthApi.getPrivate(profiles),
    ...options,
  });
  const coverageQuery = useQuery({
    queryKey: ['data-coverage', profiles],
    queryFn: () => insightsApi.getDataCoverage(profiles),
    ...options,
  });
  const removedQuery = useQuery({
    queryKey: ['data-removed', profiles],
    queryFn: () => dataHealthApi.getRemoved(profiles),
    ...options,
  });

  return (
    <>
      <Panel
        title="THEIR NUMBERS AGAINST OURS"
        src="profiles.reported_total_films vs profile_films"
        blurb="Letterboxd states a total on every profile page. Where ours is lower, we say so — that difference is the single most honest number in the product."
        caveat={countsQuery.data?.caveat}
      >
        {panelState({
          isLoading: countsQuery.isLoading || (selectionLoading && !enabled),
          error: countsQuery.error,
          isEmpty: (countsQuery.data?.profiles.length ?? 0) === 0,
          onRetry: () => countsQuery.refetch(),
          errorTitle: 'Counts could not be compared',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: { title: 'No profiles selected', body: 'Choose at least one profile above.' },
        }) ?? (
          <Rows
            columns="minmax(0,1fr) 66px 66px 60px"
            head={['PROFILE', ['THEIRS', 'right'], ['OURS', 'right'], ['GAP', 'right']]}
            rows={(countsQuery.data?.profiles ?? []).map((entry) => {
              const tone =
                entry.gap === null
                  ? 'var(--muted)'
                  : entry.gap <= 0
                    ? 'var(--ok)'
                    : entry.gap < 100
                      ? 'var(--accent)'
                      : 'var(--bad)';
              return {
                cells: [
                  cell(`@${entry.username}`),
                  // Never read is not zero, and printing 0 here would claim we
                  // had checked and found nothing.
                  cell(entry.theirs === null ? 'not read' : entry.theirs.toLocaleString(), {
                    align: 'right',
                    size: '10.5px',
                    tone: entry.theirs === null ? 'var(--dim)' : 'var(--muted)',
                  }),
                  cell(entry.ours.toLocaleString(), { align: 'right', tone: 'var(--ink)' }),
                  cell(entry.gap === null ? '—' : entry.gap.toLocaleString(), {
                    align: 'right',
                    tone,
                  }),
                ],
              };
            })}
          />
        )}
      </Panel>

      <Panel
        title="PRIVATE SURFACES WE CAN SEE BUT NOT READ"
        src="profiles.reported_* vs what we hold"
        blurb="We can often tell something exists without being able to read it. Saying so is better than an empty panel that looks like nothing happened."
        caveat={privateQuery.data?.caveat}
      >
        {panelState({
          isLoading: privateQuery.isLoading || (selectionLoading && !enabled),
          error: privateQuery.error,
          isEmpty: (privateQuery.data?.profiles.length ?? 0) === 0,
          onRetry: () => privateQuery.refetch(),
          errorTitle: 'Private surfaces could not be inferred',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'Nothing detectably hidden',
            body: 'Every stated total we can check matches what we hold. A surface with no stated total cannot be checked this way, so this is not a guarantee.',
          },
        }) ?? (
          <Rows
            columns="minmax(0,0.8fr) minmax(0,1.6fr)"
            head={['PROFILE', 'WHAT IS HIDDEN']}
            rows={(privateQuery.data?.profiles ?? []).map((entry) => ({
              cells: [
                cell(`@${entry.username}`),
                cell(entry.hidden.join(' · '), {
                  font: 's',
                  size: '10px',
                  tone: 'var(--ink3)',
                  wrap: true,
                }),
              ],
            }))}
          />
        )}
      </Panel>

      <Panel
        title="WHAT EACH VIEW IS WAITING FOR"
        src="feature readiness"
        blurb="Was “feature readiness · coverage: blocked”. Each row names the panel, what state it is in, and what it is waiting on."
        caveat="A blocked view is not broken. It is a question this selection cannot answer yet, and the blocker beside it is the thing that would change that."
      >
        {panelState({
          isLoading: coverageQuery.isLoading || (selectionLoading && !enabled),
          error: coverageQuery.error,
          isEmpty: (coverageQuery.data?.feature_readiness.length ?? 0) === 0,
          onRetry: () => coverageQuery.refetch(),
          errorTitle: 'Readiness could not be read',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: { title: 'No readiness reported', body: 'Nothing has been computed for this selection yet.' },
        }) ?? (
          <Rows
            columns="minmax(0,1.1fr) 100px minmax(0,1.3fr)"
            head={['PANEL', ['STATE', 'right'], 'NEEDS']}
            rows={(coverageQuery.data?.feature_readiness ?? []).map((entry) => {
              const state = READINESS_LABEL[entry.status];
              const blockers = entry.blockers.length ? entry.blockers : entry.warnings;
              return {
                cells: [
                  cell(FEATURE_LABEL[entry.feature] ?? entry.feature, {
                    font: 's',
                    size: '11px',
                    tone: 'var(--ink)',
                  }),
                  cell(state.label, { align: 'right', size: '10px', tone: state.tone }),
                  // Repeating "answered in full" beside a state that already
                  // says so is nine lines of noise down the column.
                  cell(blockers.length ? blockers.join(' ') : '—', {
                    font: 's',
                    size: '10px',
                    tone: 'var(--dim)',
                    wrap: true,
                  }),
                ],
              };
            })}
          />
        )}
      </Panel>

      <Panel
        title="GONE SINCE THE LAST CHECK"
        src="removed_at"
        blurb="Rows that were there last time and are not now. Was “soft-removed”. Nothing is deleted — it moves here and then to Lost & found."
        caveat={removedQuery.data?.caveat}
      >
        {panelState({
          isLoading: removedQuery.isLoading || (selectionLoading && !enabled),
          error: removedQuery.error,
          isEmpty: (removedQuery.data?.removed.length ?? 0) === 0,
          severity: 'quiet',
          onRetry: () => removedQuery.refetch(),
          errorTitle: 'Removals could not be read',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'Nothing has disappeared',
            body: 'No row that was present in an earlier read has stopped appearing. Two authoritative reads are needed before anything can show up here at all.',
          },
        }) ?? (
          <Rows
            columns="minmax(0,1fr) 84px 70px 80px"
            head={['PROFILE', ['KIND', 'right'], ['ROWS', 'right'], ['NOTICED', 'right']]}
            rows={(removedQuery.data?.removed ?? []).map((entry) => ({
              cells: [
                cell(`@${entry.username}`),
                cell(entry.kind, { align: 'right', size: '9.5px', tone: 'var(--muted)' }),
                cell(entry.rows.toLocaleString(), { align: 'right', tone: 'var(--accent)' }),
                cell(
                  entry.noticed_at
                    ? new Date(entry.noticed_at).toLocaleDateString('en-GB', {
                        day: '2-digit',
                        month: 'short',
                      })
                    : '—',
                  { align: 'right', size: '10px', tone: 'var(--ink3)' },
                ),
              ],
            }))}
          />
        )}
      </Panel>
    </>
  );
}
