'use client';

import { useCallback, useMemo, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { motion } from 'framer-motion';
import { useQuery } from '@tanstack/react-query';
import { Trophy, Waypoints } from 'lucide-react';

import FollowNetwork from '../components/FollowNetwork';
import { followGraphApi } from '../services/api';
import { useScopedProfiles } from '../hooks/useScopedProfiles';

/** One direction of a centred profile's connections, coloured to match the
 *  edges already drawn in the graph above. */
function ConnectionGroup({
  label,
  tone,
  usernames,
  empty,
}: {
  label: string;
  tone: 'mutual' | 'outward' | 'inward';
  usernames: string[];
  empty: string;
}) {
  const accent =
    tone === 'mutual'
      ? 'border-emerald-400/25 bg-emerald-400/[0.07] text-emerald-200'
      : 'border-cinema-400/25 bg-cinema-500/[0.07] text-cinema-200';
  return (
    <div className="rounded-lg border border-white/[0.07] bg-black/20 p-3">
      <p className="flex items-baseline justify-between text-xs font-semibold text-white/60">
        {label}
        <span className="tabular-nums text-white/35">{usernames.length}</span>
      </p>
      {usernames.length === 0 ? (
        <p className="mt-2 text-[11px] text-white/30">{empty}</p>
      ) : (
        <ul className="mt-2 flex flex-wrap gap-1.5">
          {usernames.map((username) => (
            <li key={username} className={`rounded-md border px-2 py-0.5 text-[11px] ${accent}`}>
              @{username}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function Network() {
  // `?focus=` lets another page hand off to one profile's corner of the graph.
  // My Profiles links here rather than claiming to draw a graph of its own.
  const searchParams = useSearchParams();
  const requestedFocus = searchParams.get('focus');

  // The graph reports which profile is centred so the ranking can follow the
  // selection instead of sitting underneath it contradicting the view.
  const [focusedUsername, setFocusedUsername] = useState<string | null>(null);
  const handleFocusChange = useCallback((username: string | null) => {
    setFocusedUsername(username);
  }, []);

  const profilesQuery = useScopedProfiles();
  const completedProfiles = useMemo(
    () => (profilesQuery.data ?? []).filter((profile) => profile.scraping_status === 'completed'),
    [profilesQuery.data],
  );

  // Shares the FollowNetwork component's query key, so the graph and the
  // ranking render from one request.
  const mutualsQuery = useQuery({
    queryKey: ['follow-mutuals', 'network'],
    queryFn: () => followGraphApi.getMutuals([]),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  const ranking = useMemo(() => {
    const rollups = mutualsQuery.data?.rollups ?? {};
    return Object.entries(rollups)
      .map(([username, rollup]) => ({
        username,
        follows: rollup.follows_in_group,
        followedBy: rollup.followed_by_in_group,
        total: rollup.follows_in_group + rollup.followed_by_in_group,
      }))
      .filter((entry) => entry.total > 0)
      .sort((a, b) => b.total - a.total || a.username.localeCompare(b.username))
      .slice(0, 8);
  }, [mutualsQuery.data]);

  /**
   * What the centred profile's own connections look like.
   *
   * While one person is centred, a leaderboard answers a question about the
   * whole group instead of about them. Everything below is already on screen in
   * the graph -- the green and orange edges, the dashed untracked ones -- so
   * this panel names it rather than making the reader count spokes.
   */
  const focusDetail = useMemo(() => {
    if (!focusedUsername) return null;
    const handle = focusedUsername.toLowerCase();
    const pairs = mutualsQuery.data?.pairs ?? [];

    const mutual: string[] = [];
    const follows: string[] = [];
    const followedBy: string[] = [];
    // Who each *other* member is connected to, so we can find shared circles.
    const circles = new Map<string, Set<string>>();

    for (const pair of pairs) {
      const a = pair.a.toLowerCase();
      const b = pair.b.toLowerCase();
      if (!circles.has(a)) circles.set(a, new Set());
      if (!circles.has(b)) circles.set(b, new Set());
      if (pair.a_follows_b || pair.b_follows_a) {
        circles.get(a)!.add(b);
        circles.get(b)!.add(a);
      }
      if (a !== handle && b !== handle) continue;
      const other = a === handle ? pair.b : pair.a;
      const outward = a === handle ? pair.a_follows_b : pair.b_follows_a;
      const inward = a === handle ? pair.b_follows_a : pair.a_follows_b;
      if (outward && inward) mutual.push(other);
      else if (outward) follows.push(other);
      else if (inward) followedBy.push(other);
    }

    const mine = circles.get(handle) ?? new Set<string>();
    const shared = [...circles.entries()]
      .filter(([username]) => username !== handle)
      .map(([username, theirs]) => ({
        username,
        overlap: [...theirs].filter((entry) => mine.has(entry)).length,
      }))
      .filter((entry) => entry.overlap > 0)
      .sort((left, right) => right.overlap - left.overlap || left.username.localeCompare(right.username))
      .slice(0, 4);

    return { mutual, follows, followedBy, shared, circleSize: mine.size };
  }, [focusedUsername, mutualsQuery.data]);

  // Where the centred profile sits in the ranking, so the panel answers a
  // question about the selection rather than ignoring it.
  const focusedEntry = useMemo(() => {
    if (!focusedUsername) return null;
    const index = ranking.findIndex(
      (entry) => entry.username.toLowerCase() === focusedUsername.toLowerCase(),
    );
    return index === -1 ? null : { ...ranking[index], rank: index + 1 };
  }, [focusedUsername, ranking]);

  return (
    <motion.div
      initial={{ y: 12 }}
      animate={{ y: 0 }}
      transition={{ duration: 0.4 }}
      className="space-y-6"
    >
      <header>
        <h1 className="flex items-center gap-3 text-3xl font-bold text-white text-glow">
          <Waypoints className="h-8 w-8 text-cinema-400" />
          Network
        </h1>
        <p className="mt-1 text-sm text-white/55">
          Who follows whom across the profiles you monitor
        </p>
      </header>

      <FollowNetwork
        profiles={completedProfiles}
        onFocusChange={handleFocusChange}
        initialFocus={requestedFocus}
      />

      {focusDetail ? (
        <section className="rounded-xl border border-white/10 bg-white/5 p-4">
          <h2 className="mb-3 flex flex-wrap items-baseline gap-2 text-sm font-semibold text-white/75">
            <Waypoints className="h-4 w-4 text-cinema-400" />
            @{focusedUsername}&rsquo;s connections
            <span className="text-xs font-normal text-white/40">
              {focusDetail.circleSize} inside this group
            </span>
          </h2>

          <div className="grid gap-2 sm:grid-cols-3">
            <ConnectionGroup
              label="Mutual"
              tone="mutual"
              usernames={focusDetail.mutual}
              empty="Nobody here follows them back"
            />
            <ConnectionGroup
              label="They follow"
              tone="outward"
              usernames={focusDetail.follows}
              empty="Follows nobody here one-way"
            />
            <ConnectionGroup
              label="Follow them"
              tone="inward"
              usernames={focusDetail.followedBy}
              empty="Nobody here follows them one-way"
            />
          </div>

          {focusDetail.shared.length > 0 && (
            <div className="mt-3 border-t border-white/[0.07] pt-3">
              <h3 className="text-xs font-semibold text-white/55">Moves in the same circles as</h3>
              <ul className="mt-2 flex flex-wrap gap-2">
                {focusDetail.shared.map((entry) => (
                  <li
                    key={entry.username}
                    className="rounded-lg border border-white/10 bg-black/20 px-2.5 py-1 text-xs text-white/70"
                  >
                    @{entry.username}
                    <span className="ml-1.5 text-white/35">
                      {entry.overlap} in common
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      ) : ranking.length > 0 ? (

        <section className="rounded-xl border border-white/10 bg-white/5 p-4">
          <h2 className="mb-3 flex flex-wrap items-center gap-2 text-sm font-semibold text-white/75">
            <Trophy className="h-4 w-4 text-cinema-400" />
            Most connected
            {focusedEntry && (
              <span className="text-xs font-normal text-white/40">
                @{focusedEntry.username} ranks #{focusedEntry.rank} of {ranking.length}
              </span>
            )}
          </h2>
          <ol className="grid gap-2 sm:grid-cols-2">
            {ranking.map((entry, index) => {
              const isFocused =
                focusedUsername != null &&
                entry.username.toLowerCase() === focusedUsername.toLowerCase();
              return (
                <li
                  key={entry.username}
                  aria-current={isFocused ? 'true' : undefined}
                  className={`flex items-center justify-between rounded-lg border px-3 py-2 text-sm transition-colors ${
                    isFocused
                      ? 'border-cinema-400/40 bg-cinema-500/10'
                      : focusedUsername
                        ? 'border-white/5 bg-black/20 opacity-50'
                        : 'border-white/5 bg-black/20'
                  }`}
                >
                  <span className="flex items-center gap-2 text-white/80">
                    <span className="w-5 text-right text-xs text-white/35">{index + 1}.</span>
                    @{entry.username}
                  </span>
                  <span className="text-xs text-white/45">
                    follows {entry.follows} · followed by {entry.followedBy}
                  </span>
                </li>
              );
            })}
          </ol>
        </section>
      ) : null}
    </motion.div>
  );
}
