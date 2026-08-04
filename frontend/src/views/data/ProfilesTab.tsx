'use client';

import React from 'react';
import { useQuery } from '@tanstack/react-query';

import Panel from '../../components/terminal/Panel';
import Bars from '../../components/terminal/bodies/Bars';
import Notes from '../../components/terminal/bodies/Notes';
import Rows, { cell } from '../../components/terminal/bodies/Rows';
import { BarsSkeleton, panelState } from '../../components/terminal/states';
import { useAdminScope } from '../../hooks/useAdminScope';
import {
  adminProfileRequestApi,
  dataHealthApi,
  followGraphApi,
  profileApi,
  type ProfileRequestStatus,
} from '../../services/api';

const REQUEST_STATE: Record<ProfileRequestStatus, { label: string; tone: string; next: string }> = {
  pending: {
    label: 'queued',
    tone: 'var(--ink3)',
    next: 'Waiting behind the refreshes already scheduled.',
  },
  approved: {
    label: 'accepted',
    tone: 'var(--accent)',
    next: 'Accepted — it will be read on the next full refresh.',
  },
  fulfilled: {
    label: 'done',
    tone: 'var(--ok)',
    next: 'Read and imported. It appears everywhere else in the product now.',
  },
  rejected: {
    label: 'blocked',
    tone: 'var(--bad)',
    next: 'Not readable — usually a private account, which no amount of retrying reaches.',
  },
};

function relative(iso: string | null | undefined): string {
  if (!iso) return 'never';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return 'never';
  const hours = Math.round((Date.now() - then) / 36e5);
  if (hours < 1) return 'just now';
  if (hours < 48) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function duration(seconds: number | null): string {
  if (seconds === null) return '—';
  if (seconds < 90) return `${Math.round(seconds)}s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 90) return `${minutes}m`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

export default function ProfilesTab({ profiles }: { profiles: string[] }) {
  const { isAdmin, userReady } = useAdminScope();
  const enabled = profiles.length > 0;

  const freshnessQuery = useQuery({
    queryKey: ['data-freshness', profiles],
    queryFn: () => dataHealthApi.getFreshness(profiles),
    enabled,
    staleTime: 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const requestsQuery = useQuery({
    queryKey: ['profile-requests'],
    queryFn: () => profileApi.getRequests(),
    staleTime: 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const suggestionsQuery = useQuery({
    queryKey: ['follow-suggestions', 'data'],
    queryFn: () => followGraphApi.getSuggestions({ limit: 10, minOverlap: 2 }),
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const latencyQuery = useQuery({
    queryKey: ['data-latency', profiles],
    queryFn: () => dataHealthApi.getRequestLatency(profiles),
    enabled,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const adminQueueQuery = useQuery({
    queryKey: ['admin-profile-requests'],
    queryFn: () => adminProfileRequestApi.getRequests(),
    enabled: userReady && isAdmin,
    staleTime: 60 * 1000,
    refetchOnWindowFocus: false,
  });

  return (
    <>
      <Panel
        title="EVERYONE WE HAVE SYNCED"
        src="profiles · profile_syncs"
        wide
        caveat={freshnessQuery.data?.caveat}
      >
        {panelState({
          isLoading: freshnessQuery.isLoading,
          error: freshnessQuery.error,
          isEmpty: (freshnessQuery.data?.profiles.length ?? 0) === 0,
          severity: 'fatal',
          onRetry: () => freshnessQuery.refetch(),
          errorTitle: 'Available profiles could not be loaded',
          errorBody: 'You can still request a username by hand while this is down.',
          empty: {
            title: 'Nobody synced here yet',
            body: 'Ask for a username below and it will be read on the next full refresh.',
          },
        }) ?? (
          <Rows
            columns="minmax(0,1fr) 90px 90px minmax(0,1fr)"
            // "THEY REPORT", because the figure is Letterboxd's own header
            // count, not our imported rows — for a freshly synced profile the
            // two differ, and a column named FILMS HELD showing the number we
            // do NOT hold inverted the fact. Our count is the roster's FILMS
            // column on Overview, and the gap between the two is the whole
            // subject of Data › What's missing.
            head={['PROFILE', ['WATCHES', 'right'], ['LAST READ', 'right'], 'THEY REPORT']}
            rows={(freshnessQuery.data?.profiles ?? []).map((entry) => {
              return {
                cells: [
                  cell(`@${entry.username}`),
                  cell(entry.watch_events.toLocaleString(), {
                    align: 'right',
                    tone: 'var(--ink)',
                  }),
                  cell(relative(entry.last_read_at), {
                    align: 'right',
                    size: '10px',
                    tone:
                      entry.hours_ago === null
                        ? 'var(--dim)'
                        : entry.hours_ago > 24 * 7
                          ? 'var(--bad)'
                          : entry.hours_ago > 24
                            ? 'var(--accent)'
                            : 'var(--ok)',
                  }),
                  // A header nobody has read holds no number. This used to
                  // read the tracked-profile list, which does not cover every
                  // profile on screen, and rendered a confident 0 for the ones
                  // it missed — beside their own non-zero watch count.
                  cell(
                    entry.films_held === null ? 'never read' : entry.films_held.toLocaleString(),
                    {
                      align: 'right',
                      size: '10px',
                      tone: entry.films_held === null ? 'var(--dim)' : 'var(--muted)',
                    },
                  ),
                ],
              };
            })}
          />
        )}
      </Panel>

      <Panel
        title="ASK FOR SOMEONE NEW"
        src="profile_access_requests"
        caveat="Stop watching somebody and their history stays. The store is append-only, so untracking hides a profile from the product without deleting anything."
      >
        <Notes
          items={[
            {
              label: 'Paste a Letterboxd URL or handle',
              text: (
                <>
                  Requests, tracking and the admin queue live on{' '}
                  <a href="/profiles">the profile manager</a>. We check the account is public, queue
                  a first read, and tell you which surfaces we expect to get.
                </>
              ),
            },
            {
              label: 'A first import is a baseline',
              text: 'Change-detection panels — gone quiet, changed their mind, unfollows — stay empty until the second refresh. This is stated up front rather than discovered.',
            },
            {
              label: 'An export unlocks four more panels',
              text: 'Likes, comments, pronouns and deleted history exist only in the owner’s official export. Public scraping never reaches them.',
            },
          ]}
        />
      </Panel>

      <Panel
        title="WHO TO TRACK NEXT"
        src="profile_follow_edges × profiles absence"
        blurb="Ranked by how many of the group already follow them. Same computation as the orbit panel in People, surfaced where you can act on it."
        caveat="Costs nothing to compute: it reads follow edges we already hold rather than fetching anything new."
      >
        {panelState({
          isLoading: suggestionsQuery.isLoading,
          error: suggestionsQuery.error,
          isEmpty: (suggestionsQuery.data?.suggestions.length ?? 0) === 0,
          severity: 'degraded',
          onRetry: () => suggestionsQuery.refetch(),
          errorTitle: 'Suggestions could not be loaded',
          errorBody: 'You can still request a username by hand.',
          empty: {
            title: 'No social data synced yet',
            body: 'Suggestions appear once follow lists are imported for the monitored profiles.',
          },
          skeleton: <BarsSkeleton rows={5} />,
        }) ?? (
          <Bars
            items={(suggestionsQuery.data?.suggestions ?? []).map((suggestion) => ({
              name: `@${suggestion.username}`,
              weight: suggestion.followed_by_count,
              // Counted across every monitored profile, which is what the
              // server measured. Dividing by the tab's current selection
              // produced "10 of 6".
              value: `${suggestion.followed_by_count} of ${suggestionsQuery.data?.monitored_profiles ?? '—'}`,
              sub: suggestion.already_imported ? 'synced' : 'new',
            }))}
          />
        )}
      </Panel>

      <Panel
        title="YOUR REQUEST STATUS"
        src="profile_access_requests.status"
        caveat="A rejected request is almost always a private account. Retrying will not change that, and the row says so rather than leaving it queued forever."
      >
        {panelState({
          isLoading: requestsQuery.isLoading,
          error: requestsQuery.error,
          isEmpty: (requestsQuery.data?.length ?? 0) === 0,
          severity: 'quiet',
          onRetry: () => requestsQuery.refetch(),
          errorTitle: 'Requests could not be loaded',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'No requests yet',
            body: 'Anything you ask for appears here with its state and what happens next.',
          },
        }) ?? (
          <Rows
            columns="minmax(0,1fr) 82px minmax(0,1.3fr)"
            head={['ACCOUNT', ['STATE', 'right'], 'WHAT NEXT']}
            rows={(requestsQuery.data ?? []).map((request) => {
              const state = REQUEST_STATE[request.status];
              return {
                cells: [
                  cell(`@${request.requested_username}`, { tone: 'var(--ink)' }),
                  cell(state.label, { align: 'right', size: '10px', tone: state.tone }),
                  cell(state.next, {
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
        title="HOW LONG A REQUEST ACTUALLY TAKES"
        src="profile_syncs durations"
        blurb="Measured from completed runs rather than promised."
        stats={
          latencyQuery.data && latencyQuery.data.runs
            ? [
                { big: duration(latencyQuery.data.median_seconds), unit: 'MEDIAN', tone: 'var(--accent)' },
                { big: duration(latencyQuery.data.worst_seconds), unit: 'WORST CASE' },
                { big: latencyQuery.data.runs, unit: 'RUNS MEASURED' },
              ]
            : undefined
        }
        caveat={latencyQuery.data?.caveat}
      >
        {panelState({
          isLoading: latencyQuery.isLoading,
          error: latencyQuery.error,
          isEmpty: (latencyQuery.data?.runs ?? 0) === 0,
          onRetry: () => latencyQuery.refetch(),
          errorTitle: 'Latency could not be measured',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'Nothing measurable yet',
            body: 'No completed sync carries both a start and an end time, so an estimate would be a promise rather than a figure.',
          },
        })}
      </Panel>

      {isAdmin ? (
        <Panel
          title="ADMIN · REQUEST QUEUE"
          src="profile_access_requests (admin scope)"
          blurb="Visible only under the admin scope. Everything below is somebody else asking for a profile, in the order it will run."
          caveat="Approving a request queues a first read; it does not fetch anything on its own. The queue is worked through by the refresh schedule."
        >
          {panelState({
            isLoading: adminQueueQuery.isLoading,
            error: adminQueueQuery.error,
            isEmpty: (adminQueueQuery.data?.length ?? 0) === 0,
            onRetry: () => adminQueueQuery.refetch(),
            errorTitle: 'The admin queue could not be loaded',
            errorBody: 'Every other panel on this tab is unaffected.',
            empty: {
              title: 'No profile requests yet',
              body: 'Requests arrive here the moment any account asks for a username.',
            },
          }) ?? (
            <Rows
              columns="minmax(0,1fr) minmax(0,0.8fr) 82px"
              head={['ACCOUNT', 'ASKED BY', ['STATE', 'right']]}
              rows={(adminQueueQuery.data ?? []).map((request) => ({
                cells: [
                  cell(`@${request.requested_username}`, { tone: 'var(--ink)' }),
                  cell(
                    request.requester_letterboxd_username
                      ? `@${request.requester_letterboxd_username}`
                      : 'unknown',
                    { size: '10px', tone: 'var(--muted)' },
                  ),
                  cell(REQUEST_STATE[request.status].label, {
                    align: 'right',
                    size: '10px',
                    tone: REQUEST_STATE[request.status].tone,
                  }),
                ],
              }))}
            />
          )}
        </Panel>
      ) : null}
    </>
  );
}
