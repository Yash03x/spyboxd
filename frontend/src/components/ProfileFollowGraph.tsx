'use client';

import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { ExternalLink, Waypoints } from 'lucide-react';

import { followGraphApi, type FollowGraphEdge } from '../services/api';
import { ProfileAvatar } from './insights/InsightUI';

type FollowDirection = 'following' | 'followers';

function FollowEdgeRow({ edge }: { edge: FollowGraphEdge }) {
  return (
    <li className="flex items-center gap-3 rounded-lg border border-white/[0.06] bg-black/15 px-3 py-2">
      <ProfileAvatar
        profile={{ username: edge.counterpart_username, avatar_url: edge.counterpart_avatar_url }}
        size="sm"
      />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-semibold text-white">
          {edge.counterpart_display_name || edge.counterpart_username}
        </p>
        <p className="truncate text-[11px] text-white/40">@{edge.counterpart_username}</p>
      </div>
      {edge.is_imported_profile && (
        <span className="shrink-0 rounded-md border border-emerald-400/25 bg-emerald-400/10 px-2 py-0.5 text-[10px] font-semibold text-emerald-200">
          In Spyboxd
        </span>
      )}
      {edge.counterpart_profile_url && (
        <a
          href={edge.counterpart_profile_url}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={`Open ${edge.counterpart_username} on Letterboxd`}
          className="shrink-0 rounded-md p-1.5 text-white/35 transition-colors hover:bg-white/10 hover:text-white"
        >
          <ExternalLink className="h-3.5 w-3.5" />
        </a>
      )}
    </li>
  );
}

/**
 * Expandable following/followers drawer for one profile. Quietly reports
 * "No social data synced yet" when the endpoint is missing (phase not
 * deployed), the caller lacks access, or no edges have been imported.
 */
export default function ProfileFollowGraph({ username }: { username: string }) {
  const [direction, setDirection] = useState<FollowDirection>('following');

  const graphQuery = useQuery({
    queryKey: ['follow-graph', username.toLowerCase(), direction],
    queryFn: () => followGraphApi.getFollowGraph(username, { direction }),
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const data = graphQuery.data;
  const edges = data?.edges ?? [];

  return (
    <div className="mt-3 rounded-xl border border-white/10 bg-black/20 p-3" data-testid={`follow-graph-${username}`}>
      <div className="flex items-center gap-1 rounded-lg border border-white/10 bg-black/20 p-1" role="tablist" aria-label={`Who ${username} follows and is followed by`}>
        {(['following', 'followers'] as const).map((option) => {
          const count = option === 'following' ? data?.following_count : data?.followers_count;
          const selected = direction === option;
          return (
            <button
              key={option}
              type="button"
              role="tab"
              aria-selected={selected}
              onClick={() => setDirection(option)}
              className={`flex-1 rounded-md px-3 py-1.5 text-xs font-semibold capitalize transition-colors ${
                selected ? 'bg-cinema-500 text-white shadow-glow' : 'text-white/50 hover:bg-white/5 hover:text-white'
              }`}
            >
              {option}
              {typeof count === 'number' ? ` (${count.toLocaleString()})` : ''}
            </button>
          );
        })}
      </div>

      {graphQuery.isLoading ? (
        <p className="mt-3 text-xs text-white/45">Loading follows…</p>
      ) : graphQuery.error || edges.length === 0 ? (
        <p className="mt-3 rounded-lg border border-white/[0.06] bg-black/15 p-3 text-xs text-white/45">
          No social data synced yet.
        </p>
      ) : (
        <>
          <ul className="mt-3 max-h-64 space-y-1.5 overflow-y-auto pr-1">
            {edges.map((edge) => (
              <FollowEdgeRow key={`${edge.direction}-${edge.counterpart_username}`} edge={edge} />
            ))}
          </ul>
          {data && data.total > edges.length && (
            <p className="mt-2 text-[10px] text-white/35">
              Showing {edges.length.toLocaleString()} of {data.total.toLocaleString()}.
            </p>
          )}
        </>
      )}
      {/* The actual graph is drawn on the Network page. Linking there is what
          makes the promise good, rather than a list under a graph heading. */}
      <Link
        href={`/people?tab=circle&subject=${encodeURIComponent(username)}`}
        className="mt-3 flex items-center justify-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-1.5 text-[11px] font-semibold text-white/55 transition-colors hover:bg-white/10 hover:text-white"
      >
        <Waypoints className="h-3 w-3" aria-hidden="true" />
        See @{username} in the network graph
      </Link>
    </div>
  );
}
