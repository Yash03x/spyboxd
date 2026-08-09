'use client';

import React from 'react';
import { useQuery } from '@tanstack/react-query';

import Panel from '../../components/terminal/Panel';
import Notes from '../../components/terminal/bodies/Notes';
import Rows, { cell } from '../../components/terminal/bodies/Rows';
import { panelState } from '../../components/terminal/states';
import { dataHealthApi } from '../../services/api';

function relative(iso: string | null): string {
  if (!iso) return 'never';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return 'never';
  const hours = Math.round((Date.now() - then) / 36e5);
  // A scheduled next-poll time is in the future, and rounding that to "just
  // now" turned a wait into a claim that it had already happened.
  if (hours < 0) {
    const ahead = Math.abs(hours);
    return ahead < 48 ? `in ${Math.max(ahead, 1)}h` : `in ${Math.round(ahead / 24)}d`;
  }
  if (hours < 1) return 'just now';
  if (hours < 48) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function duration(seconds: number | null): string {
  if (seconds === null) return '—';
  if (seconds < 90) return `${Math.round(seconds)}s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 90) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  // Days, once there are any. A wait that is mostly somebody getting round
  // to starting a batch reads as "2d 3h", not as "51h 0m".
  if (hours >= 24) return `${Math.floor(hours / 24)}d ${hours % 24}h`;
  return `${hours}h ${minutes % 60}m`;
}

export default function RefreshesTab({
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

  const ledgerQuery = useQuery({
    queryKey: ['data-ledger', profiles],
    queryFn: () => dataHealthApi.getLedger(profiles),
    ...options,
  });
  const feedsQuery = useQuery({
    queryKey: ['data-feeds', profiles],
    queryFn: () => dataHealthApi.getFeeds(profiles),
    ...options,
  });
  const importersQuery = useQuery({
    queryKey: ['data-importers', profiles],
    queryFn: () => dataHealthApi.getImporters(profiles),
    ...options,
  });
  const latencyQuery = useQuery({
    queryKey: ['data-latency', profiles],
    queryFn: () => dataHealthApi.getRequestLatency(profiles),
    ...options,
  });

  return (
    <>
      <Panel
        title="PER-SURFACE REFRESH LEDGER"
        src="profile_syncs · sync_datasets"
        wide
        blurb="Every surface, every profile, when it was last read and what came back. This was buried in admin and is the honest answer to “why is this panel empty”."
        caveat={ledgerQuery.data?.caveat}
      >
        {panelState({
          isLoading: ledgerQuery.isLoading || (selectionLoading && !enabled),
          error: ledgerQuery.error,
          isEmpty: (ledgerQuery.data?.surfaces.length ?? 0) === 0,
          onRetry: () => ledgerQuery.refetch(),
          errorTitle: 'The ledger could not be read',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'No completed sync yet',
            body: 'Nothing has been read for this selection, so there is no ledger to show.',
          },
        }) ?? (
          <Rows
            columns="minmax(0,0.9fr) 76px 76px 68px minmax(0,1.1fr)"
            head={[
              'SURFACE',
              ['LAST RUN', 'right'],
              ['ROWS', 'right'],
              ['PROFILES', 'right'],
              'RESULT',
            ]}
            rows={(ledgerQuery.data?.surfaces ?? []).map((surface) => ({
              cells: [
                cell(surface.surface, { font: 's' }),
                cell(relative(surface.last_run), {
                  align: 'right',
                  size: '10px',
                  tone: 'var(--muted)',
                }),
                cell(surface.rows.toLocaleString(), { align: 'right', tone: 'var(--ink)' }),
                cell(`${surface.profiles_covered} / ${surface.profiles_selected}`, {
                  align: 'right',
                  size: '10px',
                  tone: 'var(--accent)',
                }),
                cell(surface.result, {
                  font: 's',
                  size: '10px',
                  tone: surface.authoritative_profiles
                    ? 'var(--ok)'
                    : surface.profiles_covered
                      ? 'var(--accent)'
                      : 'var(--muted)',
                  wrap: true,
                }),
              ],
            }))}
          />
        )}
      </Panel>

      <Panel
        title="FEED HEALTH AND BACKOFF"
        src="profile_feed_states.next_poll_at"
        blurb="When a feed refuses us we slow down rather than retry harder. The wait is shown because it explains a stale panel better than a spinner does."
        caveat={feedsQuery.data?.caveat}
      >
        {panelState({
          isLoading: feedsQuery.isLoading || (selectionLoading && !enabled),
          error: feedsQuery.error,
          isEmpty: (feedsQuery.data?.feeds.length ?? 0) === 0,
          onRetry: () => feedsQuery.refetch(),
          errorTitle: 'Feed health could not be read',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'No incremental feed for this selection',
            body: 'These profiles are refreshed on demand only, so they have no backoff state rather than a healthy one.',
          },
        }) ?? (
          <Rows
            columns="minmax(0,1fr) 82px minmax(0,1.2fr)"
            head={['PROFILE', ['NEXT TRY', 'right'], 'WHY']}
            rows={(feedsQuery.data?.feeds ?? []).map((feed) => ({
              cells: [
                cell(`@${feed.username}`),
                cell(feed.next_poll_at ? relative(feed.next_poll_at) : '—', {
                  align: 'right',
                  size: '10px',
                  tone:
                    feed.tone === 'bad'
                      ? 'var(--bad)'
                      : feed.tone === 'warn'
                        ? 'var(--accent)'
                        : 'var(--ok)',
                }),
                cell(feed.why, { font: 's', size: '10px', tone: 'var(--dim)', wrap: true }),
              ],
            }))}
          />
        )}
      </Panel>

      <Panel
        title="READ BY AN OLD IMPORTER"
        src="profile_syncs.importer_version"
        blurb="Profiles last read by a version that did not collect everything the current one does. A full refresh fixes it; until then the missing fields are marked, not faked."
        caveat={importersQuery.data?.caveat}
      >
        {panelState({
          isLoading: importersQuery.isLoading || (selectionLoading && !enabled),
          error: importersQuery.error,
          isEmpty: (importersQuery.data?.profiles.length ?? 0) === 0,
          onRetry: () => importersQuery.refetch(),
          errorTitle: 'Importer versions could not be read',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: { title: 'No profiles selected', body: 'Choose at least one profile above.' },
        }) ?? (
          <Rows
            columns="minmax(0,1fr) 70px minmax(0,1.2fr)"
            head={['PROFILE', ['VER', 'right'], 'WHAT THAT COSTS']}
            rows={(importersQuery.data?.profiles ?? []).map((entry) => ({
              cells: [
                cell(`@${entry.username}`),
                cell(entry.importer_version ?? 'never', {
                  align: 'right',
                  size: '10px',
                  tone: entry.is_current ? 'var(--ok)' : 'var(--accent)',
                }),
                cell(entry.missing, {
                  font: 's',
                  size: '10px',
                  tone: entry.is_current ? 'var(--dim)' : 'var(--accent)',
                  wrap: true,
                }),
              ],
            }))}
          />
        )}
      </Panel>

      <Panel
        title="FULL REFRESH · OWNER EXPORT"
        src="profile_access_requests · exports"
        stats={
          latencyQuery.data && latencyQuery.data.runs
            ? [
                {
                  big: duration(latencyQuery.data.median_seconds),
                  unit: 'MEDIAN',
                  tone: 'var(--accent)',
                },
                { big: duration(latencyQuery.data.worst_seconds), unit: 'WORST CASE' },
              ]
            : undefined
        }
        caveat={latencyQuery.data?.caveat}
      >
        <Notes
          items={[
            {
              label: 'Full refresh',
              text: 'Re-reads every surface for one profile from the beginning, at a rate the feed tolerates. Was called “residential full sync”, which described our plumbing rather than the outcome.',
            },
            {
              label: 'Nothing is overwritten',
              text: 'A refresh appends and marks what it can no longer see. Films that vanish move to Lost & found instead of disappearing.',
            },
            {
              label: 'Owner export',
              text: 'Upload the official Letterboxd export and four panels light up that scraping cannot reach: likes, comments, pronouns and deleted history.',
            },
          ]}
        />
      </Panel>
    </>
  );
}
