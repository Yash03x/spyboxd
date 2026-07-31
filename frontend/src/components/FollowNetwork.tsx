'use client';

import React, { useId, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { motion } from 'framer-motion';
import { Share2 } from 'lucide-react';

import { followGraphApi, type FollowMutualPair, type ProfileInfo } from '../services/api';

const VIEW_WIDTH = 760;
const VIEW_HEIGHT = 640;
const CENTER_X = VIEW_WIDTH / 2;
const CENTER_Y = VIEW_HEIGHT / 2;
const RING_RADIUS = 232;
const NODE_RADIUS = 26;
const EDGE_GAP = NODE_RADIUS + 8;

const MUTUAL_COLOR = '#34d399'; // emerald-400
const ONEWAY_COLOR = '#f57c00'; // cinema-400

interface NetworkNode {
  username: string;
  key: string;
  x: number;
  y: number;
  cos: number;
  avatarUrl: string | null;
}

interface NetworkEdge {
  pair: FollowMutualPair;
  from: NetworkNode;
  to: NetworkNode;
  mutual: boolean;
}

/** Trim a segment so it starts/ends at the node boundaries instead of centers. */
function edgeSegment(from: NetworkNode, to: NetworkNode) {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const length = Math.hypot(dx, dy) || 1;
  const ux = dx / length;
  const uy = dy / length;
  return {
    x1: from.x + ux * EDGE_GAP,
    y1: from.y + uy * EDGE_GAP,
    x2: to.x - ux * EDGE_GAP,
    y2: to.y - uy * EDGE_GAP,
  };
}

function NodeAvatar({ node, clipId }: { node: NetworkNode; clipId: string }) {
  const [failed, setFailed] = useState(false);

  if (node.avatarUrl && !failed) {
    return (
      <image
        href={node.avatarUrl}
        x={node.x - NODE_RADIUS}
        y={node.y - NODE_RADIUS}
        width={NODE_RADIUS * 2}
        height={NODE_RADIUS * 2}
        preserveAspectRatio="xMidYMid slice"
        clipPath={`url(#${clipId})`}
        onError={() => setFailed(true)}
      />
    );
  }

  return (
    <>
      <circle cx={node.x} cy={node.y} r={NODE_RADIUS} fill="rgba(229, 81, 0, 0.16)" />
      <text
        x={node.x}
        y={node.y}
        textAnchor="middle"
        dominantBaseline="central"
        fill="#fbcd9a"
        fontSize={18}
        fontWeight={700}
        style={{ textTransform: 'uppercase' }}
      >
        {node.username.slice(0, 2).toUpperCase()}
      </text>
    </>
  );
}

/**
 * SVG node-edge network of the tracked profiles' follow relationships.
 * Nodes sit on a stable circle (deterministic order = the API's profiles
 * array); mutual follows render as solid emerald lines, one-way follows as
 * orange lines with an arrowhead toward the followed profile.
 */
export default function FollowNetwork({ profiles }: { profiles: ProfileInfo[] }) {
  const reactId = useId();
  const [hovered, setHovered] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  // No explicit profiles: the endpoint defaults to the caller's full
  // accessible/tracked set. Quiet by design on 404 (endpoint not deployed).
  const networkQuery = useQuery({
    queryKey: ['follow-mutuals', 'network'],
    queryFn: () => followGraphApi.getMutuals([]),
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const avatarByUsername = useMemo(() => {
    const map = new Map<string, string | null>();
    profiles.forEach((profile) => {
      map.set(profile.username.toLowerCase(), profile.profile_image_url ?? profile.avatar_url ?? null);
    });
    return map;
  }, [profiles]);

  const nodes = useMemo<NetworkNode[]>(() => {
    const usernames = networkQuery.data?.profiles ?? [];
    const count = usernames.length;
    return usernames.map((username, index) => {
      const angle = -Math.PI / 2 + (index * 2 * Math.PI) / Math.max(count, 1);
      const cos = Math.cos(angle);
      return {
        username,
        key: username.toLowerCase(),
        x: CENTER_X + RING_RADIUS * cos,
        y: CENTER_Y + RING_RADIUS * Math.sin(angle),
        cos,
        avatarUrl: avatarByUsername.get(username.toLowerCase()) ?? null,
      };
    });
  }, [networkQuery.data?.profiles, avatarByUsername]);

  const nodeByKey = useMemo(() => new Map(nodes.map((node) => [node.key, node])), [nodes]);

  const edges = useMemo<NetworkEdge[]>(() => {
    const pairs = networkQuery.data?.pairs ?? [];
    const result: NetworkEdge[] = [];
    pairs.forEach((pair) => {
      if (!pair.a_follows_b && !pair.b_follows_a) return;
      const nodeA = nodeByKey.get(pair.a.toLowerCase());
      const nodeB = nodeByKey.get(pair.b.toLowerCase());
      if (!nodeA || !nodeB) return;
      // Orient one-way edges from follower to followed so the arrowhead
      // always points at the followed profile.
      const from = pair.mutual || pair.a_follows_b ? nodeA : nodeB;
      const to = from === nodeA ? nodeB : nodeA;
      result.push({ pair, from, to, mutual: pair.mutual });
    });
    return result;
  }, [networkQuery.data?.pairs, nodeByKey]);

  const neighborsByKey = useMemo(() => {
    const map = new Map<string, Set<string>>();
    edges.forEach((edge) => {
      if (!map.has(edge.from.key)) map.set(edge.from.key, new Set());
      if (!map.has(edge.to.key)) map.set(edge.to.key, new Set());
      map.get(edge.from.key)!.add(edge.to.key);
      map.get(edge.to.key)!.add(edge.from.key);
    });
    return map;
  }, [edges]);

  const mutualCount = edges.filter((edge) => edge.mutual).length;
  const onewayCount = edges.length - mutualCount;
  const activeKey = selected ?? hovered;
  const activeNode = activeKey ? nodeByKey.get(activeKey) ?? null : null;
  const activeRollup = useMemo(() => {
    if (!activeNode) return null;
    const rollups = networkQuery.data?.rollups ?? {};
    const entry = Object.entries(rollups).find(([username]) => username.toLowerCase() === activeNode.key);
    return entry ? entry[1] : null;
  }, [activeNode, networkQuery.data?.rollups]);

  if (networkQuery.error) return null;

  return (
    <motion.section
      aria-label="Follow network"
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.1 }}
      className="panel-insight p-5"
      data-testid="follow-network"
    >
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <Share2 className="h-4 w-4 text-cinema-300" aria-hidden="true" />
          <h2 className="text-lg font-bold text-white">Network</h2>
          {!networkQuery.isLoading && nodes.length > 0 && (
            <span className="text-xs text-white/40">
              {nodes.length} profiles &middot; {mutualCount} mutual &middot; {onewayCount} one-way
            </span>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-4 text-[11px] text-white/50">
          <span className="flex items-center gap-1.5">
            <svg width="26" height="8" viewBox="0 0 26 8" aria-hidden="true">
              <line x1="1" y1="4" x2="25" y2="4" stroke={MUTUAL_COLOR} strokeWidth="2" strokeLinecap="round" />
            </svg>
            Mutual
          </span>
          <span className="flex items-center gap-1.5">
            <svg width="26" height="8" viewBox="0 0 26 8" aria-hidden="true">
              <line x1="1" y1="4" x2="19" y2="4" stroke={ONEWAY_COLOR} strokeWidth="2" strokeLinecap="round" />
              <polygon points="19,0.5 25,4 19,7.5" fill={ONEWAY_COLOR} />
            </svg>
            Follows
          </span>
        </div>
      </header>

      {networkQuery.isLoading ? (
        <p className="mt-6 pb-2 text-center text-sm text-white/40">Mapping who follows whom&hellip;</p>
      ) : edges.length === 0 ? (
        <p className="mt-6 pb-2 text-center text-sm text-white/40">
          No follow connections between these profiles yet.
        </p>
      ) : (
        <>
          <div className="mx-auto mt-2 w-full max-w-3xl">
            <svg
              viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
              className="h-auto w-full"
              role="img"
              aria-label={`Follow network of ${nodes.length} tracked profiles: ${mutualCount} mutual, ${onewayCount} one-way`}
            >
              <defs>
                <marker
                  id={`${reactId}-arrow`}
                  viewBox="0 0 10 10"
                  refX="9"
                  refY="5"
                  markerWidth="9"
                  markerHeight="9"
                  markerUnits="userSpaceOnUse"
                  orient="auto-start-reverse"
                >
                  <path d="M 0 0 L 10 5 L 0 10 z" fill={ONEWAY_COLOR} />
                </marker>
                {nodes.map((node) => (
                  <clipPath key={node.key} id={`${reactId}-clip-${node.key}`}>
                    <circle cx={node.x} cy={node.y} r={NODE_RADIUS} />
                  </clipPath>
                ))}
              </defs>

              {/* Click-away target to clear a selected node. */}
              <rect
                x="0"
                y="0"
                width={VIEW_WIDTH}
                height={VIEW_HEIGHT}
                fill="transparent"
                onClick={() => setSelected(null)}
              />

              <g>
                {edges.map((edge) => {
                  const segment = edgeSegment(edge.from, edge.to);
                  const isActive = activeKey !== null && (edge.from.key === activeKey || edge.to.key === activeKey);
                  const opacity = activeKey === null ? 0.55 : isActive ? 0.95 : 0.08;
                  return (
                    <line
                      key={`${edge.pair.a}-${edge.pair.b}`}
                      x1={segment.x1}
                      y1={segment.y1}
                      x2={segment.x2}
                      y2={segment.y2}
                      stroke={edge.mutual ? MUTUAL_COLOR : ONEWAY_COLOR}
                      strokeWidth={isActive ? 2.5 : 1.75}
                      strokeLinecap="round"
                      opacity={opacity}
                      markerEnd={edge.mutual ? undefined : `url(#${reactId}-arrow)`}
                      style={{ transition: 'opacity 0.2s ease, stroke-width 0.2s ease' }}
                    />
                  );
                })}
              </g>

              <g>
                {nodes.map((node) => {
                  const isActive = node.key === activeKey;
                  const isNeighbor = activeKey !== null && (neighborsByKey.get(activeKey)?.has(node.key) ?? false);
                  const dimmed = activeKey !== null && !isActive && !isNeighbor;
                  const labelRadial = RING_RADIUS + NODE_RADIUS + 12;
                  const labelX = CENTER_X + ((node.x - CENTER_X) / RING_RADIUS) * labelRadial;
                  const labelY = CENTER_Y + ((node.y - CENTER_Y) / RING_RADIUS) * labelRadial;
                  const anchor = node.cos > 0.35 ? 'start' : node.cos < -0.35 ? 'end' : 'middle';
                  return (
                    <g
                      key={node.key}
                      role="button"
                      tabIndex={0}
                      aria-pressed={selected === node.key}
                      aria-label={`Highlight ${node.username}'s follow connections`}
                      style={{ cursor: 'pointer', opacity: dimmed ? 0.25 : 1, transition: 'opacity 0.2s ease', outline: 'none' }}
                      onMouseEnter={() => setHovered(node.key)}
                      onMouseLeave={() => setHovered(null)}
                      onFocus={() => setHovered(node.key)}
                      onBlur={() => setHovered(null)}
                      onClick={() => setSelected((current) => (current === node.key ? null : node.key))}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter' || event.key === ' ') {
                          event.preventDefault();
                          setSelected((current) => (current === node.key ? null : node.key));
                        }
                      }}
                    >
                      <circle cx={node.x} cy={node.y} r={NODE_RADIUS + 3} fill="#0f172a" />
                      <NodeAvatar node={node} clipId={`${reactId}-clip-${node.key}`} />
                      <circle
                        cx={node.x}
                        cy={node.y}
                        r={NODE_RADIUS + 1.5}
                        fill="none"
                        stroke={isActive ? '#ffffff' : isNeighbor ? MUTUAL_COLOR : 'rgba(245, 124, 0, 0.4)'}
                        strokeWidth={isActive ? 2.5 : 1.5}
                        style={{ transition: 'stroke 0.2s ease' }}
                      />
                      <text
                        x={labelX}
                        y={labelY}
                        textAnchor={anchor}
                        dominantBaseline="central"
                        fill={isActive ? '#ffffff' : 'rgba(255, 255, 255, 0.55)'}
                        fontSize={13}
                        fontWeight={600}
                      >
                        {node.username}
                      </text>
                    </g>
                  );
                })}
              </g>
            </svg>
          </div>
          <p className="min-h-5 text-center text-xs text-white/45" aria-live="polite">
            {activeNode && activeRollup
              ? `@${activeNode.username} follows ${activeRollup.follows_in_group} in this group, followed by ${activeRollup.followed_by_in_group}`
              : activeNode
                ? `@${activeNode.username}`
                : 'Hover or tap a profile to trace its connections.'}
          </p>
        </>
      )}
    </motion.section>
  );
}
