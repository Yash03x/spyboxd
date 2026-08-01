'use client';

import React, { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { ArrowLeft, Share2 } from 'lucide-react';

import { followGraphApi, type ProfileInfo } from '../services/api';

/** Radius every disc is *drawn* at; layout scales the disc group, never this. */
const NODE_RADIUS = 26;
/** Clear space kept between neighbouring discs on a ring. */
const NODE_GAP = 16;
/** Smallest ring the full view uses, so a 5-profile group still fills the frame. */
const MIN_RING_RADIUS = 232;
/** Past this the ring stops growing and the discs shrink instead. */
const MAX_RING_RADIUS = 560;
const MIN_NODE_SCALE = 0.58;
const EDGE_GAP = 8;
const CENTER_SCALE = 1.3;
const HIDDEN_SCALE = 0.55;
/** Degree scaling stays inside this band: hubs read bigger, nothing distorts. */
const HUB_SCALE_MIN = 0.86;
const HUB_SCALE_MAX = 1.16;
/** Room for the halo and the keyboard focus ring outside the biggest disc. */
const RING_PAD = 12;
/** Frame left outside the ring for radial labels, and for a bare ring. */
const LABEL_PAD_X = 132;
const LABEL_PAD_Y = 48;
const BARE_PAD = 26;
/** Adjacent labels sit on alternating radii; this is the step between tiers. */
const LABEL_TIER_STEP = 16;
/** Above this many nodes on a ring, labels only appear on hover/focus. */
const LABEL_ALL_MAX = 24;
/** Narrower than this and radial labels are unreadable at any node count. */
const COMPACT_WIDTH = 520;
/** Space an ego-view label needs outside its ring when the full view has none. */
const EGO_LABEL_REACH = 166;
/** The ego ring never pulls in tighter than this, however cramped the frame. */
const MIN_EGO_RADIUS = 150;
/** Ego view stays readable only if the fan of leaves stays small. */
const MAX_EXTRA_LEAVES = 10;

const MUTUAL_COLOR = '#34d399'; // emerald-400
const ONEWAY_COLOR = '#f57c00'; // cinema-400
const UNTRACKED_STROKE = 'rgba(255, 255, 255, 0.32)';

interface Point {
  x: number;
  y: number;
}

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
  /** Slot on its ring, so labels can alternate radius to dodge each other. */
  ringIndex: number;
  ringCount: number;
}

interface RenderEdge {
  id: string;
  fromKey: string;
  toKey: string;
  mutual: boolean;
  /** Only exists inside ego view (counterpart outside the tracked group). */
  extra: boolean;
}

/** Everything the circle geometry needs, derived from group size + container. */
interface Layout {
  width: number;
  height: number;
  centerX: number;
  centerY: number;
  ringRadius: number;
  /** Baseline disc scale before the per-node degree boost. */
  nodeScale: number;
  /** How hard edges are pulled toward the middle, 0 = straight chords. */
  bundle: number;
  /** Enough room in the frame for a label on every node. */
  labels: boolean;
  compact: boolean;
  /** Multiplier keeping revealed labels legible when the viewBox is scaled down. */
  fontScale: number;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

/** Ring radius that keeps `count` discs of `scale` at least NODE_GAP apart. */
function fitRingRadius(count: number, scale: number): number {
  if (count <= 1) return 0;
  return (2 * NODE_RADIUS * scale + NODE_GAP) / (2 * Math.sin(Math.PI / count));
}

/** Largest disc scale that still leaves NODE_GAP between `count` discs at `radius`. */
function fitNodeScale(count: number, radius: number): number {
  if (count <= 1) return 1;
  return (2 * radius * Math.sin(Math.PI / count) - NODE_GAP) / (2 * NODE_RADIUS);
}

/**
 * Circle geometry for `count` nodes. The ring is sized from the chord between
 * neighbours (2R·sin(pi/n) has to clear one disc plus a gap) rather than a fixed
 * radius, and the viewBox grows with it so nothing ever leaves the frame.
 */
function buildLayout(count: number, containerWidth: number): Layout {
  const compact = containerWidth > 0 && containerWidth < COMPACT_WIDTH;
  // Discs also give up a little size past ~22 nodes, so the ring (and with it
  // the viewBox) grows more slowly than the node count.
  const wantedScale = count <= 22 ? 1 : clamp(1 - (count - 22) * 0.009, 0.62, 1);
  const ringRadius = clamp(fitRingRadius(count, wantedScale), MIN_RING_RADIUS, MAX_RING_RADIUS);
  // Past MAX_RING_RADIUS the ring can no longer absorb more nodes, so the fit
  // comes out of the disc size instead.
  const nodeScale = clamp(Math.min(wantedScale, fitNodeScale(count, ringRadius)), MIN_NODE_SCALE, 1);
  const labels = !compact && count <= LABEL_ALL_MAX;
  const reach = ringRadius + NODE_RADIUS * nodeScale * HUB_SCALE_MAX + RING_PAD;
  const width = Math.round(2 * (reach + (labels ? LABEL_PAD_X : BARE_PAD)));
  const height = Math.round(2 * (reach + (labels ? LABEL_PAD_Y : BARE_PAD)));

  return {
    width,
    height,
    centerX: width / 2,
    centerY: height / 2,
    ringRadius,
    nodeScale,
    // Denser graphs need a harder pull to separate into bundles; a five-node
    // ring only needs a hint of a curve.
    bundle: clamp(0.3 + count * 0.01, 0.3, 0.55),
    labels,
    compact,
    fontScale: containerWidth > 0 ? clamp(width / containerWidth, 1, 2.4) : 1,
  };
}

/**
 * How far names may run before they are clipped, and whether they need to
 * alternate radius. A label collides with its neighbour once its width passes
 * the tangential run between them (2*pi*R_label / n), so the budget shrinks as
 * the ring fills up; tiering adjacent labels doubles that run.
 */
function labelPlan(count: number): { maxChars: number; tiers: boolean } {
  return {
    maxChars: count <= 8 ? 16 : count <= 18 ? 12 : 10,
    tiers: count > 14,
  };
}

function labelTier(index: number, count: number): number {
  // An odd ring wraps onto itself, so the last label needs a third radius or it
  // lands beside index 0 on the same tier.
  if (count % 2 === 1 && index === count - 1) return 2;
  return index % 2;
}

function truncateLabel(username: string, maxChars: number): string {
  return username.length <= maxChars ? username : `${username.slice(0, maxChars - 1)}…`;
}

function ringPlacement(
  index: number,
  count: number,
  radius: number,
  center: Point,
  scale: number,
): Placement {
  const angle = -Math.PI / 2 + (index * 2 * Math.PI) / Math.max(count, 1);
  const cos = Math.cos(angle);
  const sin = Math.sin(angle);
  return {
    x: center.x + radius * cos,
    y: center.y + radius * sin,
    cos,
    sin,
    scale,
    opacity: 1,
    radius: NODE_RADIUS * scale,
    visible: true,
    isCenter: false,
    ringIndex: index,
    ringCount: count,
  };
}

/**
 * Leaves fan out on a ring that grows with the number of connections, keeping
 * the geometry the small fan has always used and stopping at `cap` so the ego
 * view always fits the frame the full view already claimed.
 */
function egoRingRadius(count: number, cap: number): number {
  const base = Math.min(246, Math.max(196, 150 + count * 9));
  const wanted = Math.max(base, fitRingRadius(count, 1));
  return Math.min(wanted, Math.max(cap, MIN_EGO_RADIUS));
}

/** Rough width for a label chip; SVG cannot measure text up front. */
function labelChipWidth(username: string): number {
  return Math.max(104, username.length * 8.6 + 26);
}

function lerpPoint(from: Point, to: Point, amount: number): Point {
  return { x: from.x + (to.x - from.x) * amount, y: from.y + (to.y - from.y) * amount };
}

/** Step off a node's centre toward a target, so edges start at the disc edge. */
function offsetToward(node: Placement, target: Point, fallback: Point): Point {
  let dx = target.x - node.x;
  let dy = target.y - node.y;
  let length = Math.hypot(dx, dy);
  if (length < 0.01) {
    dx = fallback.x - node.x;
    dy = fallback.y - node.y;
    length = Math.hypot(dx, dy);
  }
  if (length < 0.01) return { x: node.x, y: node.y };
  const step = node.radius + EDGE_GAP;
  return { x: node.x + (dx / length) * step, y: node.y + (dy / length) * step };
}

const round = (value: number) => value.toFixed(2);

/**
 * Bundled edge: a cubic whose control points pull each endpoint toward the
 * centre. Every edge therefore leaves its node aimed at the middle, so one
 * profile's connections read as a fan rather than n straight chords crossing
 * the disc. Two consequences worth keeping: an edge between opposite nodes is
 * still a straight line (its controls sit on the chord), and the whole curve
 * stays inside the ring, which leaves the label band outside it free of ink.
 */
function edgePath(from: Placement, to: Placement, center: Point, bundle: number): string {
  const start = offsetToward(from, lerpPoint(from, center, bundle), to);
  const end = offsetToward(to, lerpPoint(to, center, bundle), from);
  const c1 = lerpPoint(start, center, bundle);
  const c2 = lerpPoint(end, center, bundle);
  return `M ${round(start.x)} ${round(start.y)} C ${round(c1.x)} ${round(c1.y)} ${round(c2.x)} ${round(c2.y)} ${round(end.x)} ${round(end.y)}`;
}

/** Same command shape as edgePath, collapsed to a point for enter/exit. */
function collapsedPath(center: Point): string {
  const x = round(center.x);
  const y = round(center.y);
  return `M ${x} ${y} C ${x} ${y} ${x} ${y} ${x} ${y}`;
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
 * Full view: nodes sit on a circle sized from the group (deterministic order =
 * the API's profiles array), each disc scaled by how connected the profile is
 * inside the group; mutual follows render as solid emerald curves, one-way
 * follows as orange curves with an arrowhead toward the followed profile.
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
  // Tracked separately from `hovered`: a node sliding out from under a resting
  // cursor fires mouseleave, which must not erase the keyboard focus ring.
  const [keyboardFocusKey, setKeyboardFocusKey] = useState<string | null>(null);
  const [container, setContainer] = useState<HTMLDivElement | null>(null);
  const [containerWidth, setContainerWidth] = useState(0);
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

  // The viewBox scales the graph to the container, so how much room a label
  // really has is a rendered-pixel question, not a viewBox one.
  useEffect(() => {
    if (!container || typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width ?? 0;
      setContainerWidth((current) => (Math.abs(current - width) < 1 ? current : width));
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, [container]);

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

  const rollupByKey = useMemo(() => {
    const map = new Map<string, { follows_in_group: number; followed_by_in_group: number }>();
    Object.entries(networkQuery.data?.rollups ?? {}).forEach(([username, rollup]) => {
      map.set(username.toLowerCase(), rollup);
    });
    return map;
  }, [networkQuery.data?.rollups]);

  // Degree inside the group drives disc size, so hubs are visible at a glance.
  const hubScaleByKey = useMemo(() => {
    const degrees = new Map<string, number>();
    groupNodes.forEach((node) => {
      const rollup = rollupByKey.get(node.key);
      degrees.set(
        node.key,
        rollup
          ? rollup.follows_in_group + rollup.followed_by_in_group
          : neighborsByKey.get(node.key)?.size ?? 0,
      );
    });
    const values = Array.from(degrees.values());
    const min = values.length ? Math.min(...values) : 0;
    const max = values.length ? Math.max(...values) : 0;
    const span = max - min;
    const scales = new Map<string, number>();
    degrees.forEach((degree, key) => {
      // sqrt keeps the growth closer to area, so twice the connections does not
      // read as four times the disc.
      const t = span > 0 ? Math.sqrt((degree - min) / span) : 1;
      scales.set(key, span > 0 ? HUB_SCALE_MIN + (HUB_SCALE_MAX - HUB_SCALE_MIN) * t : 1);
    });
    return scales;
  }, [groupNodes, rollupByKey, neighborsByKey]);

  const layout = useMemo(
    () => buildLayout(groupNodes.length, containerWidth),
    [groupNodes.length, containerWidth],
  );

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

  const ringCount = focusKey ? egoLeafKeys.length : groupNodes.length;
  const labelsOn = !layout.compact && ringCount > 0 && ringCount <= LABEL_ALL_MAX;
  const { maxChars, tiers } = labelPlan(ringCount);

  const placements = useMemo(() => {
    const map = new Map<string, Placement>();
    const count = groupNodes.length;
    const center = { x: layout.centerX, y: layout.centerY };
    const leafIndexByKey = new Map(egoLeafKeys.map((key, index) => [key, index]));
    const leafCount = egoLeafKeys.length;
    // A group too big for labels has no label padding in the frame, so the ego
    // ring has to pull in far enough to fit the labels it does show.
    const egoCap =
      !layout.labels && leafCount <= LABEL_ALL_MAX && !layout.compact
        ? Math.min(layout.ringRadius, Math.min(layout.width, layout.height) / 2 - EGO_LABEL_REACH)
        : layout.ringRadius;
    const leafRadius = egoRingRadius(leafCount, egoCap);
    const leafScale = clamp(fitNodeScale(leafCount, leafRadius), MIN_NODE_SCALE, 1);

    groupNodes.forEach((node, index) => {
      const hub = hubScaleByKey.get(node.key) ?? 1;
      const ring = ringPlacement(index, count, layout.ringRadius, center, layout.nodeScale * hub);
      if (!focusKey) {
        map.set(node.key, ring);
        return;
      }
      if (node.key === focusKey) {
        map.set(node.key, {
          x: center.x,
          y: center.y,
          cos: 0,
          sin: 1,
          scale: CENTER_SCALE,
          opacity: 1,
          radius: NODE_RADIUS * CENTER_SCALE,
          visible: true,
          isCenter: true,
          ringIndex: 0,
          ringCount: 1,
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
      map.set(node.key, ringPlacement(leafIndex, leafCount, leafRadius, center, leafScale * hub));
    });

    extraNodes.forEach((node) => {
      const leafIndex = leafIndexByKey.get(node.key);
      if (leafIndex === undefined) return;
      // One known in-group tie (the centre), so they sit at the bottom of the
      // degree band rather than dwarfing the tracked leaves.
      map.set(
        node.key,
        ringPlacement(leafIndex, leafCount, leafRadius, center, leafScale * HUB_SCALE_MIN),
      );
    });

    return map;
  }, [groupNodes, focusKey, egoLeafKeys, extraNodes, layout, hubScaleByKey]);

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
  const captionRollup = captionNode ? rollupByKey.get(captionNode.key) ?? null : null;

  const exitEgoView = useCallback(() => {
    const previous = focusKey;
    setFocusKey(null);
    // Hand focus back to the node that was centred and keep it highlighted, so
    // focus is never dropped on the floor when the ego view tears down.
    setHovered(previous);
    if (previous) {
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
  const center: Point = { x: layout.centerX, y: layout.centerY };

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
    const revealed = isCenter || isHovered || keyboardFocusKey === node.key;
    // With labels off, a revealed one is drawn inward on a chip: outside the
    // ring there is no frame left for it, inside there is nothing but space.
    const inwardLabel = !labelsOn && !isCenter;
    const labelScale = inwardLabel || isCenter ? layout.fontScale : 1;
    const labelText = revealed ? node.username : truncateLabel(node.username, maxChars);
    const labelVisible = isCenter || revealed || labelsOn;
    const chipVisible = isCenter || (inwardLabel && revealed);
    const chipWidth = labelChipWidth(labelText) * labelScale;
    const tier = labelsOn && tiers && !isCenter ? labelTier(placement.ringIndex, placement.ringCount) : 0;
    // A reveal chip is axis-aligned, so a node at 3 o'clock needs the chip's own
    // half-width of clearance to stay inside the ring, one at 12 o'clock only
    // its half-height. Anything less and the chip runs out of the frame.
    const labelOffset = inwardLabel
      ? -(
          NODE_RADIUS * placement.scale +
          12 +
          Math.abs(placement.cos) * (chipWidth / 2) +
          Math.abs(placement.sin) * 15 * labelScale
        )
      : NODE_RADIUS * placement.scale + 14 + tier * LABEL_TIER_STEP;
    const labelX = isCenter ? 0 : placement.cos * labelOffset;
    // The centre label sits clear of the halo ring, on an opaque chip so it
    // stays readable where a connection line runs underneath it.
    const labelY = isCenter
      ? NODE_RADIUS * CENTER_SCALE + 18 + 12 * labelScale
      : placement.sin * labelOffset;
    const anchor =
      isCenter || inwardLabel
        ? 'middle'
        : placement.cos > 0.35
          ? 'start'
          : placement.cos < -0.35
            ? 'end'
            : 'middle';
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
        initial={node.inGroup ? false : { x: center.x, y: center.y, opacity: 0 }}
        animate={{ x: placement.x, y: placement.y, opacity }}
        exit={{ x: center.x, y: center.y, opacity: 0 }}
        transition={transition}
        aria-hidden={placement.visible ? undefined : true}
      >
        {/* Interaction lives on the disc alone, so the hit area stays a circle
            centred on the node rather than stretching over its label. */}
        <motion.g
          ref={(element: SVGGElement | null) => {
            nodeRefs.current.set(node.key, element);
          }}
          animate={{ scale: placement.scale }}
          transition={transition}
          role={interactive ? 'button' : undefined}
          tabIndex={interactive ? 0 : -1}
          aria-label={interactive ? ariaLabel : undefined}
          aria-pressed={interactive ? focusKey === node.key : undefined}
          style={{
            cursor: interactive ? 'pointer' : 'default',
            pointerEvents: placement.visible ? 'auto' : 'none',
            outline: 'none',
          }}
          onMouseEnter={() => (interactive ? setHovered(node.key) : undefined)}
          onMouseLeave={() => setHovered((current) => (current === node.key ? null : current))}
          onFocus={(event) => {
            if (!interactive) return;
            setHovered(node.key);
            // Ring for keyboard focus only; a plain click should not draw one.
            let focusVisible = true;
            try {
              focusVisible = event.currentTarget.matches(':focus-visible');
            } catch {
              focusVisible = true;
            }
            if (focusVisible) setKeyboardFocusKey(node.key);
          }}
          onBlur={() => {
            setHovered((current) => (current === node.key ? null : current));
            setKeyboardFocusKey((current) => (current === node.key ? null : current));
          }}
          onClick={() => (interactive ? activateNode(node) : undefined)}
          onKeyDown={(event) => {
            if (!interactive) return;
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault();
              activateNode(node);
            }
          }}
        >
          <title>{node.inGroup ? `@${node.username}` : `@${node.username} is not a tracked profile`}</title>
          <circle r={NODE_RADIUS + 6} fill="transparent" />
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
          {keyboardFocusKey === node.key && (
            <circle
              r={NODE_RADIUS + (isCenter ? 13 : 6)}
              fill="none"
              stroke="#ffffff"
              strokeWidth={2}
              strokeDasharray="4 4"
              opacity={0.9}
            />
          )}
        </motion.g>
        <motion.g
          animate={{ x: labelX, y: labelY, opacity: labelVisible ? 1 : 0 }}
          transition={transition}
          style={{ pointerEvents: 'none' }}
        >
          <motion.rect
            x={-chipWidth / 2}
            y={(isCenter ? -15 : -13) * labelScale}
            width={chipWidth}
            height={(isCenter ? 44 : 26) * labelScale}
            rx={12 * labelScale}
            fill="rgba(9, 12, 20, 0.88)"
            stroke="rgba(255, 255, 255, 0.12)"
            strokeWidth={1}
            opacity={0}
            initial={false}
            animate={{ opacity: chipVisible ? 1 : 0 }}
            transition={transition}
          />
          <text
            x={0}
            y={0}
            textAnchor={anchor}
            dominantBaseline="central"
            fill={
              isCenter || isHovered
                ? '#ffffff'
                : node.inGroup
                  ? 'rgba(255, 255, 255, 0.55)'
                  : 'rgba(255, 255, 255, 0.38)'
            }
            fontSize={(isCenter ? 15 : 13) * labelScale}
            fontWeight={600}
          >
            {labelText}
          </text>
          <motion.text
            x={0}
            y={17 * labelScale}
            textAnchor="middle"
            dominantBaseline="central"
            fill="rgba(251, 205, 154, 0.9)"
            fontSize={11 * labelScale}
            fontWeight={600}
            opacity={0}
            initial={false}
            animate={{ opacity: isCenter ? 1 : 0 }}
            transition={transition}
          >
            Open deep dive
          </motion.text>
        </motion.g>
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
          <div ref={setContainer} className="relative mx-auto mt-2 w-full max-w-3xl">
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
              viewBox={`0 0 ${layout.width} ${layout.height}`}
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
                width={layout.width}
                height={layout.height}
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
                    const untracked = extraByKey.has(edge.fromKey) || extraByKey.has(edge.toKey);

                    return (
                      <motion.path
                        key={edge.id}
                        initial={edge.extra ? { d: collapsedPath(center), opacity: 0 } : false}
                        animate={{ d: edgePath(from, to, center, layout.bundle), opacity }}
                        exit={{ d: collapsedPath(center), opacity: 0 }}
                        transition={transition}
                        fill="none"
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
              ? `Centred on @${focusNode.username}${captionRollup ? ` (follows ${captionRollup.follows_in_group} here, followed by ${captionRollup.followed_by_in_group})` : ''}. Open the centre for the deep dive, pick a connection to walk on, or press Escape.`
              : captionNode && captionRollup
                ? `@${captionNode.username} follows ${captionRollup.follows_in_group} in this group, followed by ${captionRollup.followed_by_in_group}. Click to centre the graph on them.`
                : captionNode
                  ? `@${captionNode.username}`
                  : labelsOn
                    ? 'Hover a profile to trace its connections, or click one to centre the graph on it.'
                    : 'Hover or tap a profile to name it and trace its connections; click to centre the graph on it.'}
          </p>
        </>
      )}
    </motion.section>
  );
}
