'use client';

import { useCallback, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import { useQuery } from '@tanstack/react-query';
import { Trophy, Waypoints } from 'lucide-react';

import FollowNetwork from '../components/FollowNetwork';
import { followGraphApi } from '../services/api';
import { useScopedProfiles } from '../hooks/useScopedProfiles';

export default function Network() {
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
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
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

      <FollowNetwork profiles={completedProfiles} onFocusChange={handleFocusChange} />

      {ranking.length > 0 && (
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
      )}
    </motion.div>
  );
}
