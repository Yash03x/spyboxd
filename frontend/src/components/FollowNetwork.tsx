'use client';

import React, { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { ArrowLeft, Share2 } from 'lucide-react';

import { followGraphApi, type ProfileInfo } from '../services/api';

const VIEW_WIDTH = 760;
const VIEW_HEIGHT = 640;
const CENTER_X = VIEW_WIDTH / 2;
const CENTER_Y = VIEW_HEIGHT / 2;
const RING_RADIUS = 232;
const NODE_RADIUS = 26;
const EDGE_GAP = 8;
const CENTER_SCALE = 1.3;
const HIDDEN_SCALE = 0.55;
/** Ego view stays readable only if the fan of leaves stays small. */
const MAX_EXTRA_LEAVES = 10;

const MUTUAL_COLOR = '#34d399'; // emerald-400
const ONEWAY_COLOR = '#f57c00'; // cinema-400
const UNTRACKED_STROKE = 'rgba(255, 255, 255, 0.32)';

interface GraphNode {
  key: string;
  username: string;
  avatarUrl: string | null;
  /** Member of the tracked group returned by the mutuals endpoint. */
  inGroup: boolean;
}

interface Placement {
  x: number;
  y: number;
  cos: number;
  sin: number;
  scale: number;
  opacity: number;
  /** Node radius after scaling, used to trim edge endpoints. */
  radius: number;
  /** Whether the node takes part in interaction at this layout. */
  visible: boolean;
  isCenter: boolean;
}

interface RenderEdge {
  id: string;
  fromKey: string;
  toKey: string;
  mutual: boolean;
  /** Only exists inside ego view (counterpart outside the tracked group). */
  extra: boolean;
}

function ringPlacement(index: number, count: number, radius: number, scale = 1): Placement {
  const angle = -Math.PI / 2 + (index * 2 * Math.PI) / Math.max(count, 1);
  const cos = Math.cos(angle);
  const sin = Math.sin(angle);
  return {
    x: CENTER_X + radius * cos,
    y: CENTER_Y + radius * sin,
    cos,
    sin,
    scale,
    opacity: 1,
    radius: NODE_RADIUS * scale,
    visible: true,
    isCenter: false,
  };
}

/** Leaves fan out on a ring that grows with the number of connections. */
function egoRingRadius(count: number): number {
  return Math.min(238, Math.max(150, 118 + count * 9));
}

/** Trim a segment so it starts/ends at the node boundaries instead of centers. */
function edgeSegment(from: Placement, to: Placement) {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const length = Math.hypot(dx, dy) || 1;
  const ux = dx / length;
  const uy = dy / length;
  return {
    x1: from.x + ux * (from.radius + EDGE_GAP),
    y1: from.y + uy * (from.radius + EDGE_GAP),
    x2: to.x - ux * (to.radius + EDGE_GAP),
    y2: to.y - uy * (to.radius + EDGE_GAP),
  };
}

function NodeAvatar({
  username,
  avatarUrl,
  clipId,
  muted,
}: {
  username: string;
  avatarUrl: string | null;
  clipId: string;
  muted: boolean;
}) {
  const [failed, setFailed] = useState(false);

  if (avatarUrl && !failed) {
    return (
      <image
        href={avatarUrl}
        x={-NODE_RADIUS}
        y={-NODE_RADIUS}
        width={NODE_RADIUS * 2}
        height={NODE_RADIUS * 2}
        preserveAspectRatio="xMidYMid slice"
        clipPath={`url(#${clipId})`}
        opacity={muted ? 0.55 : 1}
        onError={() => setFailed(true)}
      />
    );
  }

  return (
    <>
      <circle r={NODE_RADIUS} fill={muted ? 'rgba(255, 255, 255, 0.07)' : 'rgba(229, 81, 0, 0.16)'} />
      <text
        textAnchor="middle"
        dominantBaseline="central"
        fill={muted ? 'rgba(255, 255, 255, 0.45)' : '#fbcd9a'}
        fontSize={18}
        fontWeight={700}
        style={{ textTransform: 'uppercase' }}
      >
        {username.slice(0, 2).toUpperCase()}
      </text>
    </>
  );
}

/**
 * SVG node-edge network of the tracked profiles' follow relationships.
 *
 * Full view: nodes sit on a stable circle (deterministic order = the API's
 * profiles array); mutual follows render as solid emerald lines, one-way
 * follows as orange lines with an arrowhead toward the followed profile.
 *
 * Ego view: clicking a node springs it to the centre, fans its connections
 * around it and fades everything unrelated out. From there the centre opens
 * the profile's deep dive and any tracked leaf re-centres the graph, so the
 * follow network can be walked one hop at a time.
 */
export default function FollowNetwork({ profiles }: { profiles: ProfileInfo[] }) {
  const reactId = useId();
  const router = useRouter();
  const reduceMotion = useReducedMotion();
  const [hovered, setHovered] = useState<string | null>(null);
  const [focusKey, setFocusKey] = useState<string | null>(null);
  const nodeRefs = useRef(new Map<string, SVGGElement | null>());

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

  const groupNodes = useMemo<GraphNode[]>(() => {
    const usernames = networkQuery.data?.profiles ?? [];
    return usernames.map((username) => ({
      key: username.toLowerCase(),
      username,
      avatarUrl: avatarByUsername.get(username.toLowerCase()) ?? null,
      inGroup: true,
    }));
  }, [networkQuery.data?.profiles, avatarByUsername]);

  const groupIndexByKey = useMemo(
    () => new Map(groupNodes.map((node, index) => [node.key, index])),
    [groupNodes],
  );

  const groupEdges = useMemo<RenderEdge[]>(() => {
    const pairs = networkQuery.data?.pairs ?? [];
    const result: RenderEdge[] = [];
    pairs.forEach((pair) => {
      if (!pair.a_follows_b && !pair.b_follows_a) return;
      const keyA = pair.a.toLowerCase();
      const keyB = pair.b.toLowerCase();
      if (!groupIndexByKey.has(keyA) || !groupIndexByKey.has(keyB)) return;
      // Orient one-way edges from follower to followed so the arrowhead
      // always points at the followed profile.
      const fromKey = pair.mutual || pair.a_follows_b ? keyA : keyB;
      const toKey = fromKey === keyA ? keyB : keyA;
      result.push({ id: `g:${keyA}|${keyB}`, fromKey, toKey, mutual: pair.mutual, extra: false });
    });
    return result;
  }, [networkQuery.data?.pairs, groupIndexByKey]);

  const neighborsByKey = useMemo(() => {
    const map = new Map<string, Set<string>>();
    groupEdges.forEach((edge) => {
      if (!map.has(edge.fromKey)) map.set(edge.fromKey, new Set());
      if (!map.has(edge.toKey)) map.set(edge.toKey, new Set());
      map.get(edge.fromKey)!.add(edge.toKey);
      map.get(edge.toKey)!.add(edge.fromKey);
    });
    return map;
  }, [groupEdges]);

  // Drop the ego view if a refetch removes the focused profile from the group.
  useEffect(() => {
    if (focusKey && groupNodes.length > 0 && !groupIndexByKey.has(focusKey)) {
      setFocusKey(null);
    }
  }, [focusKey, groupIndexByKey, groupNodes.length]);

  const focusNode = useMemo(
    () => (focusKey ? groupNodes.find((node) => node.key === focusKey) ?? null : null),
    [focusKey, groupNodes],
  );

  // Optional richer per-person edges, including counterparts outside the
  // tracked group. Failures stay silent: the group-only ego view still works.
  const egoQuery = useQuery({
    queryKey: ['follow-graph', 'ego', focusNode?.username ?? ''],
    queryFn: () => followGraphApi.getFollowGraph(focusNode?.username ?? '', { direction: 'both', limit: 80 }),
    enabled: Boolean(focusNode),
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const extraNodes = useMemo(() => {
    if (!focusNode || egoQuery.isError) return [];
    const collected = new Map<
      string,
      { username: string; avatarUrl: string | null; follows: boolean; followedBy: boolean; position: number }
    >();

    (egoQuery.data?.edges ?? []).forEach((edge) => {
      if (edge.removed_at) return;
      const key = edge.counterpart_username?.toLowerCase();
      if (!key || key === focusNode.key || groupIndexByKey.has(key)) return;
      const current = collected.get(key) ?? {
        username: edge.counterpart_username,
        avatarUrl: null,
        follows: false,
        followedBy: false,
        position: Number.MAX_SAFE_INTEGER,
      };
      if (edge.direction === 'following') current.follows = true;
      else current.followedBy = true;
      current.avatarUrl = current.avatarUrl ?? edge.counterpart_avatar_url ?? null;
      current.position = Math.min(current.position, edge.position ?? Number.MAX_SAFE_INTEGER);
      collected.set(key, current);
    });

    return Array.from(collected.entries())
      .map(([key, value]) => ({ key, ...value, mutual: value.follows && value.followedBy }))
      .sort(
        (a, b) =>
          Number(b.mutual) - Number(a.mutual) ||
          a.position - b.position ||
          a.username.localeCompare(b.username),
      )
      .slice(0, MAX_EXTRA_LEAVES);
  }, [focusNode, egoQuery.data?.edges, egoQuery.isError, groupIndexByKey]);

  // Leaves keep the ring's angular order so the collapse into ego view reads
  // as a fold-in rather than a shuffle; outside counterparts come last.
  const egoLeafKeys = useMemo(() => {
    if (!focusKey) return [] as string[];
    const groupNeighbors = Array.from(neighborsByKey.get(focusKey) ?? [])
      .sort((a, b) => (groupIndexByKey.get(a) ?? 0) - (groupIndexByKey.get(b) ?? 0));
    return [...groupNeighbors, ...extraNodes.map((node) => node.key)];
  }, [focusKey, neighborsByKey, groupIndexByKey, extraNodes]);

  const placements = useMemo(() => {
    const map = new Map<string, Placement>();
    const count = groupNodes.length;
    const leafIndexByKey = new Map(egoLeafKeys.map((key, index) => [key, index]));
    const leafCount = egoLeafKeys.length;
    const leafRadius = egoRingRadius(leafCount);

    groupNodes.forEach((node, index) => {
      const ring = ringPlacement(index, count, RING_RADIUS);
      if (!focusKey) {
        map.set(node.key, ring);
        return;
      }
      if (node.key === focusKey) {
        map.set(node.key, {
          x: CENTER_X,
          y: CENTER_Y,
          cos: 0,
          sin: 1,
          scale: CENTER_SCALE,
          opacity: 1,
          radius: NODE_RADIUS * CENTER_SCALE,
          visible: true,
          isCenter: true,
        });
        return;
      }
      const leafIndex = leafIndexByKey.get(node.key);
      if (leafIndex === undefined) {
        // Unrelated to the focus: stay put, fade and shrink away.
        map.set(node.key, {
          ...ring,
          scale: HIDDEN_SCALE,
          opacity: 0,
          radius: NODE_RADIUS * HIDDEN_SCALE,
          visible: false,
        });
        return;
      }
      map.set(node.key, ringPlacement(leafIndex, leafCount, leafRadius));
    });

    extraNodes.forEach((node) => {
      const leafIndex = leafIndexByKey.get(node.key);
      if (leafIndex === undefined) return;
      map.set(node.key, ringPlacement(leafIndex, leafCount, leafRadius));
    });

    return map;
  }, [groupNodes, focusKey, egoLeafKeys, extraNodes]);

  const renderEdges = useMemo<RenderEdge[]>(() => {
    if (!focusKey) return groupEdges;
    const extras = extraNodes.map<RenderEdge>((node) => ({
      id: `x:${focusKey}|${node.key}`,
      fromKey: node.followedBy && !node.follows ? node.key : focusKey,
      toKey: node.followedBy && !node.follows ? focusKey : node.key,
      mutual: node.mutual,
      extra: true,
    }));
    return [...groupEdges, ...extras];
  }, [groupEdges, extraNodes, focusKey]);

  const mutualCount = groupEdges.filter((edge) => edge.mutual).length;
  const onewayCount = groupEdges.length - mutualCount;
  const hoverNode = hovered ? groupNodes.find((node) => node.key === hovered) ?? null : null;
  const captionNode = focusNode ?? hoverNode;
  const rollupFor = useCallback(
    (key: string) => {
      const rollups = networkQuery.data?.rollups ?? {};
      const entry = Object.entries(rollups).find(([username]) => username.toLowerCase() === key);
      return entry ? entry[1] : null;
    },
    [networkQuery.data?.rollups],
  );
  const captionRollup = captionNode ? rollupFor(captionNode.key) : null;

  const exitEgoView = useCallback(() => {
    const previous = focusKey;
    setFocusKey(null);
    setHovered(null);
    if (previous) {
      // Hand keyboard focus back to the node that was centred.
      requestAnimationFrame(() => nodeRefs.current.get(previous)?.focus());
    }
  }, [focusKey]);

  const activateNode = useCallback(
    (node: GraphNode) => {
      if (!focusKey) {
        setFocusKey(node.key);
        setHovered(null);
        return;
      }
      if (node.key === focusKey) {
        router.push(`/analysis?profile=${encodeURIComponent(node.username)}`);
        return;
      }
      if (node.inGroup) {
        setFocusKey(node.key);
        setHovered(null);
      }
    },
    [focusKey, router],
  );

  useEffect(() => {
    if (!focusKey) return undefined;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') exitEgoView();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [focusKey, exitEgoView]);

  const transition = useMemo(
    () =>
      reduceMotion
        ? { duration: 0 }
        : {
            type: 'spring' as const,
            stiffness: 150,
            damping: 22,
            mass: 0.9,
            opacity: { type: 'tween' as const, duration: 0.3, ease: 'easeOut' as const },
          },
    [reduceMotion],
  );

  const extraByKey = useMemo(() => new Map(extraNodes.map((node) => [node.key, node])), [extraNodes]);
  const hasUntracked = focusKey !== null && extraNodes.length > 0;

  const renderNode = (node: GraphNode) => {
    const placement = placements.get(node.key);
    if (!placement) return null;

    const isCenter = placement.isCenter;
    const isHovered = hovered === node.key;
    const isNeighborOfHover =
      !focusKey && hovered !== null && (neighborsByKey.get(hovered)?.has(node.key) ?? false);
    const hoverDimmed = !focusKey && hovered !== null && !isHovered && !isNeighborOfHover;
    const opacity = placement.opacity * (hoverDimmed ? 0.25 : 1);
    // Untracked counterparts have no Analysis page and cannot be re-centred.
    const interactive = placement.visible && node.inGroup;
    const labelOffset = NODE_RADIUS * placement.scale + 14;
    const labelX = isCenter ? 0 : placement.cos * labelOffset;
    const labelY = isCenter ? labelOffset + 4 : placement.sin * labelOffset;
    const anchor = isCenter ? 'middle' : placement.cos > 0.35 ? 'start' : placement.cos < -0.35 ? 'end' : 'middle';
    const ringStroke = !node.inGroup
      ? UNTRACKED_STROKE
      : isCenter || isHovered
        ? '#ffffff'
        : isNeighborOfHover
          ? MUTUAL_COLOR
          : 'rgba(245, 124, 0, 0.4)';
    const ariaLabel = isCenter
      ? `Open @${node.username}'s deep dive analysis`
      : node.inGroup
        ? `Centre the network on @${node.username}`
        : `@${node.username}, not a tracked profile`;

    return (
      <motion.g
        key={node.key}
        ref={(element: SVGGElement | null) => {
          nodeRefs.current.set(node.key, element);
        }}
        initial={node.inGroup ? false : { x: CENTER_X, y: CENTER_Y, opacity: 0 }}
        animate={{ x: placement.x, y: placement.y, opacity }}
        exit={{ x: CENTER_X, y: CENTER_Y, opacity: 0 }}
        transition={transition}
        role={interactive ? 'button' : undefined}
        tabIndex={interactive ? 0 : -1}
        aria-hidden={placement.visible ? undefined : true}
        aria-label={interactive ? ariaLabel : undefined}
        aria-pressed={interactive ? focusKey === node.key : undefined}
        style={{
          cursor: interactive ? 'pointer' : 'default',
          pointerEvents: placement.visible ? 'auto' : 'none',
          outline: 'none',
        }}
        onMouseEnter={() => (interactive ? setHovered(node.key) : undefined)}
        onMouseLeave={() => setHovered(null)}
        onFocus={() => (interactive ? setHovered(node.key) : undefined)}
        onBlur={() => setHovered(null)}
        onClick={() => (interactive ? activateNode(node) : undefined)}
        onKeyDown={(event) => {
          if (!interactive) return;
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            activateNode(node);
          }
        }}
      >
        {!node.inGroup && <title>{`@${node.username} is not a tracked profile`}</title>}
        <motion.g animate={{ scale: placement.scale }} transition={transition}>
          <circle r={NODE_RADIUS + 3} fill="#0f172a" />
          <NodeAvatar
            username={node.username}
            avatarUrl={node.avatarUrl}
            clipId={`${reactId}-node-clip`}
            muted={!node.inGroup}
          />
          <circle
            r={NODE_RADIUS + 1.5}
            fill="none"
            stroke={ringStroke}
            strokeWidth={isCenter ? 2.5 : node.inGroup ? 1.5 : 1.25}
            strokeDasharray={node.inGroup ? undefined : '3 4'}
            style={{ transition: 'stroke 0.2s ease' }}
          />
          {isCenter && (
            <circle
              r={NODE_RADIUS + 9}
              fill="none"
              stroke="rgba(255, 255, 255, 0.18)"
              strokeWidth={1}
            />
          )}
        </motion.g>
        <motion.text
          x={0}
          y={0}
          animate={{ x: labelX, y: labelY }}
          transition={transition}
          textAnchor={anchor}
          dominantBaseline="central"
          fill={isCenter || isHovered ? '#ffffff' : node.inGroup ? 'rgba(255, 255, 255, 0.55)' : 'rgba(255, 255, 255, 0.38)'}
          fontSize={isCenter ? 15 : 13}
          fontWeight={600}
          style={{ pointerEvents: 'none' }}
        >
          {node.username}
        </motion.text>
        {isCenter && (
          <motion.text
            x={0}
            y={0}
            initial={{ opacity: 0 }}
            animate={{ x: labelX, y: labelY + 18, opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={transition}
            textAnchor="middle"
            dominantBaseline="central"
            fill="rgba(251, 205, 154, 0.85)"
            fontSize={11}
            fontWeight={600}
            style={{ pointerEvents: 'none' }}
          >
            Open deep dive
          </motion.text>
        )}
      </motion.g>
    );
  };

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
          {!networkQuery.isLoading && groupNodes.length > 0 && (
            <span className="text-xs text-white/40">
              {focusNode
                ? `@${focusNode.username} · ${egoLeafKeys.length} connection${egoLeafKeys.length === 1 ? '' : 's'}`
                : `${groupNodes.length} profiles · ${mutualCount} mutual · ${onewayCount} one-way`}
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
          {hasUntracked && (
            <span className="flex items-center gap-1.5">
              <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
                <circle
                  cx="7"
                  cy="7"
                  r="5.5"
                  fill="none"
                  stroke="rgba(255, 255, 255, 0.5)"
                  strokeWidth="1.25"
                  strokeDasharray="3 3"
                />
              </svg>
              Not tracked
            </span>
          )}
        </div>
      </header>

      {networkQuery.isLoading ? (
        <p className="mt-6 pb-2 text-center text-sm text-white/40">Mapping who follows whom&hellip;</p>
      ) : groupEdges.length === 0 ? (
        <p className="mt-6 pb-2 text-center text-sm text-white/40">
          No follow connections between these profiles yet.
        </p>
      ) : (
        <>
          <div className="relative mx-auto mt-2 w-full max-w-3xl">
            <AnimatePresence>
              {focusNode && (
                <motion.button
                  key="back-to-full"
                  type="button"
                  initial={{ opacity: 0, y: -8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -8 }}
                  transition={{ duration: reduceMotion ? 0 : 0.2 }}
                  onClick={exitEgoView}
                  className="absolute right-0 top-0 z-10 flex items-center gap-1.5 rounded-full border border-white/15 bg-black/60 px-3 py-1.5 text-xs font-semibold text-white/80 backdrop-blur transition hover:border-cinema-400/50 hover:text-white"
                >
                  <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
                  Back to full network
                </motion.button>
              )}
            </AnimatePresence>

            <svg
              viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
              className="h-auto w-full"
              role="group"
              aria-label={
                focusNode
                  ? `Follow connections for ${focusNode.username}`
                  : `Follow network of ${groupNodes.length} tracked profiles: ${mutualCount} mutual, ${onewayCount} one-way`
              }
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
                {/* Nodes draw around their own origin, so one clip serves them all. */}
                <clipPath id={`${reactId}-node-clip`}>
                  <circle r={NODE_RADIUS} />
                </clipPath>
              </defs>

              {/* Click-away target: leaves the ego view. */}
              <rect
                x="0"
                y="0"
                width={VIEW_WIDTH}
                height={VIEW_HEIGHT}
                fill="transparent"
                onClick={() => (focusKey ? exitEgoView() : setHovered(null))}
              />

              <g>
                <AnimatePresence>
                  {renderEdges.map((edge) => {
                    const from = placements.get(edge.fromKey);
                    const to = placements.get(edge.toKey);
                    if (!from || !to) return null;

                    const incidentToFocus =
                      focusKey !== null && (edge.fromKey === focusKey || edge.toKey === focusKey);
                    const incidentToHover =
                      hovered !== null && (edge.fromKey === hovered || edge.toKey === hovered);
                    const opacity = focusKey
                      ? incidentToFocus
                        ? 0.9
                        : 0
                      : hovered === null
                        ? 0.55
                        : incidentToHover
                          ? 0.95
                          : 0.08;
                    const segment = edgeSegment(from, to);
                    const untracked = extraByKey.has(edge.fromKey) || extraByKey.has(edge.toKey);

                    return (
                      <motion.line
                        key={edge.id}
                        initial={
                          edge.extra
                            ? { x1: CENTER_X, y1: CENTER_Y, x2: CENTER_X, y2: CENTER_Y, opacity: 0 }
                            : false
                        }
                        animate={{ ...segment, opacity }}
                        exit={{ x1: CENTER_X, y1: CENTER_Y, x2: CENTER_X, y2: CENTER_Y, opacity: 0 }}
                        transition={transition}
                        stroke={edge.mutual ? MUTUAL_COLOR : ONEWAY_COLOR}
                        strokeWidth={incidentToFocus || incidentToHover ? 2.5 : 1.75}
                        strokeLinecap="round"
                        strokeDasharray={untracked ? '5 5' : undefined}
                        markerEnd={edge.mutual ? undefined : `url(#${reactId}-arrow)`}
                        style={{ pointerEvents: 'none' }}
                      />
                    );
                  })}
                </AnimatePresence>
              </g>

              <g>
                {groupNodes.map((node) => renderNode(node))}
                <AnimatePresence>
                  {extraNodes.map((node) =>
                    renderNode({
                      key: node.key,
                      username: node.username,
                      avatarUrl: node.avatarUrl,
                      inGroup: false,
                    }),
                  )}
                </AnimatePresence>
              </g>
            </svg>
          </div>
          <p className="min-h-5 text-center text-xs text-white/45" aria-live="polite">
            {focusNode
              ? `Centred on @${focusNode.username}${captionRollup ? `, who follows ${captionRollup.follows_in_group} in this group and is followed by ${captionRollup.followed_by_in_group}` : ''}. Open the centre for the deep dive, pick a connection to walk on, or press Escape to go back.`
              : captionNode && captionRollup
                ? `@${captionNode.username} follows ${captionRollup.follows_in_group} in this group, followed by ${captionRollup.followed_by_in_group}. Click to centre the graph on them.`
                : captionNode
                  ? `@${captionNode.username}`
                  : 'Hover a profile to trace its connections, or click one to centre the graph on it.'}
          </p>
        </>
      )}
    </motion.section>
  );
}
