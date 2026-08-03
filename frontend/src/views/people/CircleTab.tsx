'use client';

import React from 'react';
import { useQuery } from '@tanstack/react-query';

import Panel from '../../components/terminal/Panel';
import Bars from '../../components/terminal/bodies/Bars';
import EgoGraph, { type EgoLeaf } from '../../components/terminal/bodies/EgoGraph';
import Notes from '../../components/terminal/bodies/Notes';
import Rows, { cell } from '../../components/terminal/bodies/Rows';
import { BarsSkeleton, panelState } from '../../components/terminal/states';
import { sectionHref } from '../../components/terminal/sections';
import { followGraphApi, memberArchiveApi } from '../../services/api';

/**
 * Who a comment was aimed at, where the URL says so.
 *
 * An export carries a `boxd.it` short link for most comments, which resolves
 * only by following it — something production cannot do. A full
 * `letterboxd.com/<user>/...` URL names the counterpart directly. Anything
 * else stays unresolved rather than being guessed at.
 */
function counterpartFrom(url: string): string | null {
  const match = /letterboxd\.com\/([^/?#]+)\//.exec(url);
  if (!match) return null;
  const candidate = match[1].toLowerCase();
  // Not member pages: these path segments are site sections, not usernames.
  if (['film', 'films', 'list', 'lists', 'journal', 'tag', 'search'].includes(candidate)) {
    return null;
  }
  return candidate;
}

export default function CircleTab({
  subject,
  profiles,
  onSubjectChange,
}: {
  subject: string;
  profiles: string[];
  onSubjectChange: (username: string) => void;
}) {
  const graphQuery = useQuery({
    queryKey: ['follow-graph', subject],
    queryFn: () => followGraphApi.getFollowGraph(subject, { direction: 'both', limit: 200 }),
    enabled: Boolean(subject),
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const mutualsQuery = useQuery({
    queryKey: ['follow-mutuals', profiles],
    queryFn: () => followGraphApi.getMutuals(profiles),
    enabled: profiles.length > 0,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const suggestionsQuery = useQuery({
    queryKey: ['follow-suggestions'],
    queryFn: () => followGraphApi.getSuggestions({ limit: 10, minOverlap: 2 }),
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const archiveQuery = useQuery({
    queryKey: ['member-archive', subject],
    queryFn: () => memberArchiveApi.getArchive(subject),
    enabled: Boolean(subject),
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  // The ring around one person: mutual first, then one-way, then the accounts
  // the group orbits that we hold no data for.
  const leaves: EgoLeaf[] = React.useMemo(() => {
    const edges = graphQuery.data?.edges ?? [];
    const byCounterpart = new Map<string, { following: boolean; follower: boolean; tracked: boolean }>();
    edges
      .filter((edge) => edge.removed_at === null)
      .forEach((edge) => {
        const key = edge.counterpart_username.toLowerCase();
        const entry = byCounterpart.get(key) ?? {
          following: false,
          follower: false,
          tracked: edge.is_imported_profile,
        };
        if (edge.direction === 'following') entry.following = true;
        else entry.follower = true;
        entry.tracked = entry.tracked || edge.is_imported_profile;
        byCounterpart.set(key, entry);
      });

    const all: EgoLeaf[] = Array.from(byCounterpart.entries()).map(([username, entry]) => ({
      username,
      kind: entry.following && entry.follower
        ? 'mutual'
        : entry.tracked
          ? entry.following
            ? 'follows'
            : 'followedBy'
          : 'untracked',
      tracked: entry.tracked,
    }));

    const rank = (leaf: EgoLeaf) => (leaf.kind === 'mutual' ? 0 : leaf.tracked ? 1 : 2);
    // The ring holds about a dozen before the labels collide; the rest are
    // named in the caveat rather than drawn on top of each other.
    return all.sort((a, b) => rank(a) - rank(b) || a.username.localeCompare(b.username)).slice(0, 10);
  }, [graphQuery.data]);

  const totalEdges = (graphQuery.data?.edges ?? []).filter((edge) => edge.removed_at === null).length;
  const undrawn = Math.max(0, new Set(
    (graphQuery.data?.edges ?? [])
      .filter((edge) => edge.removed_at === null)
      .map((edge) => edge.counterpart_username.toLowerCase()),
  ).size - leaves.length);

  const rollups = mutualsQuery.data?.rollups ?? {};
  const dropped = (graphQuery.data?.edges ?? []).filter((edge) => edge.removed_at !== null);

  const comments = React.useMemo(() => archiveQuery.data?.comments ?? [], [archiveQuery.data]);
  const trackedLower = React.useMemo(
    () => new Set(profiles.map((name) => name.toLowerCase())),
    [profiles],
  );

  const conversations = React.useMemo(() => {
    const counts = new Map<string, { count: number; last: string | null }>();
    comments.forEach((comment) => {
      const target = counterpartFrom(comment.target_url);
      if (!target) return;
      const entry = counts.get(target) ?? { count: 0, last: null };
      entry.count += 1;
      if (comment.commented_date && (!entry.last || comment.commented_date > entry.last)) {
        entry.last = comment.commented_date;
      }
      counts.set(target, entry);
    });
    return Array.from(counts.entries())
      .map(([username, entry]) => ({ username, ...entry, tracked: trackedLower.has(username) }))
      .sort((a, b) => b.count - a.count);
  }, [comments, trackedLower]);

  const resolvedComments = comments.filter((comment) => counterpartFrom(comment.target_url)).length;

  return (
    <>
      <Panel
        title={`FOLLOW GRAPH · @${subject.toUpperCase()} CENTRED · ${totalEdges} EDGES`}
        src="profile_follow_edges"
        wide
        blurb="The circle around one person. Solid green is mutual, solid amber is one-way, dashed is somebody the group orbits that we have never synced."
        caveat={`Click a tracked node to re-centre. ${undrawn ? `${undrawn} further counterparts are not drawn — the ring holds about ten before the labels collide.` : 'Every counterpart is drawn.'} Letterboxd's follow lists carry no timestamps at all, so the order is recency and nothing more.`}
      >
        {panelState({
          isLoading: graphQuery.isLoading,
          error: graphQuery.error,
          isEmpty: leaves.length === 0,
          severity: 'degraded',
          errorTitle: 'The follow network could not be loaded',
          errorBody: 'The graph endpoint is unavailable. Every other surface is unaffected.',
          onRetry: () => graphQuery.refetch(),
          empty: {
            title: 'No follow data synced yet',
            body: 'Following and followers come from a surface that is read on its own schedule. Until it runs, this profile has no circle we can draw.',
            cta: { label: 'SEE THE REFRESH LEDGER', href: sectionHref('data', 'refreshes') },
          },
        }) ?? <EgoGraph centre={subject} leaves={leaves} onSelect={onSubjectChange} />}
      </Panel>

      <Panel
        title="MUTUAL · THEY FOLLOW · FOLLOW THEM"
        src="profile_follow_edges counts"
        caveat="Counted inside the monitored set only. Somebody with a thousand followers has three here if three of them are tracked — this is the circle we can see, not their audience."
      >
        {panelState({
          isLoading: mutualsQuery.isLoading,
          error: mutualsQuery.error,
          isEmpty: Object.keys(rollups).length === 0,
          onRetry: () => mutualsQuery.refetch(),
          errorTitle: 'Mutuals could not be loaded',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'No social data synced yet',
            body: 'Mutuals appear once follow lists are imported for the monitored profiles.',
          },
        }) ?? (
          <Rows
            columns="minmax(0,1fr) 56px 56px 56px"
            head={['PROFILE', ['MUTUAL', 'right'], ['FOLLOWS', 'right'], ['FOLLOWED', 'right']]}
            rows={Object.entries(rollups).map(([username, counts]) => {
              const mutual = (mutualsQuery.data?.pairs ?? []).filter(
                (pair) => pair.mutual && (pair.a === username || pair.b === username),
              ).length;
              return {
                cells: [
                  cell(`@${username}`),
                  cell(String(mutual), { align: 'right', tone: 'var(--ok)' }),
                  cell(String(counts.follows_in_group), { align: 'right', tone: 'var(--ink)' }),
                  cell(String(counts.followed_by_in_group), {
                    align: 'right',
                    tone: 'var(--muted)',
                  }),
                ],
              };
            })}
          />
        )}
      </Panel>

      <Panel
        title="MOST CONNECTED"
        src="profile_follow_edges degree"
        blurb="Degree inside the monitored set: every edge in plus every edge out."
      >
        {panelState({
          isLoading: mutualsQuery.isLoading,
          error: mutualsQuery.error,
          isEmpty: Object.keys(rollups).length === 0,
          onRetry: () => mutualsQuery.refetch(),
          errorTitle: 'Degree could not be computed',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'No social data synced yet',
            body: 'Follow lists have not been imported for the monitored profiles.',
          },
          skeleton: <BarsSkeleton rows={5} />,
        }) ?? (
          <Bars
            items={Object.entries(rollups)
              .map(([username, counts]) => ({
                name: `@${username}`,
                weight: counts.follows_in_group + counts.followed_by_in_group,
                value: String(counts.follows_in_group + counts.followed_by_in_group),
                sub: `${counts.follows_in_group} out`,
              }))
              .sort((a, b) => b.weight - a.weight)}
          />
        )}
      </Panel>

      <Panel
        title="FOLLOWED AND UNFOLLOWED"
        src="profile_follow_edges.removed_at"
        blurb="An unfollow is never announced, so this is inferred from an edge disappearing between two authoritative reads."
        caveat="Two reads minimum, or nothing is shown. A first import is a baseline and records no disappearance at all."
      >
        {panelState({
          isLoading: graphQuery.isLoading,
          error: graphQuery.error,
          isEmpty: dropped.length === 0,
          severity: 'quiet',
          onRetry: () => graphQuery.refetch(),
          errorTitle: 'Follow changes could not be loaded',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'No edge has disappeared yet',
            body: 'Nothing this profile followed has stopped appearing between two reads. This fills from the second refresh onward.',
            cta: { label: 'SEE THE REFRESH LEDGER', href: sectionHref('data', 'refreshes') },
          },
        }) ?? (
          <Rows
            columns="66px minmax(0,1fr) 80px"
            head={['WHEN', 'WHAT', ['DIRECTION', 'right']]}
            rows={dropped.slice(0, 10).map((edge) => ({
              cells: [
                cell(
                  edge.removed_at
                    ? new Date(edge.removed_at).toLocaleDateString('en-GB', {
                        day: '2-digit',
                        month: 'short',
                      })
                    : '—',
                  { size: '10.5px', tone: 'var(--ink3)' },
                ),
                cell(
                  edge.direction === 'following'
                    ? `@${subject} stopped following @${edge.counterpart_username}`
                    : `@${edge.counterpart_username} stopped following @${subject}`,
                  { font: 's', size: '10.5px', wrap: true },
                ),
                cell('unfollow', { align: 'right', size: '10px', tone: 'var(--bad)' }),
              ],
            }))}
          />
        )}
      </Panel>

      <Panel
        title="ORBITED BUT NEVER SYNCED"
        src="profile_follow_edges × profiles absence"
        blurb="Accounts several of the group follow that we hold no data for. The best possible answer to “who should I track next”, and it costs nothing to compute."
      >
        {panelState({
          isLoading: suggestionsQuery.isLoading,
          error: suggestionsQuery.error,
          isEmpty: (suggestionsQuery.data?.suggestions.length ?? 0) === 0,
          onRetry: () => suggestionsQuery.refetch(),
          errorTitle: 'Suggestions could not be loaded',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'Nothing orbited that we have not synced',
            body: 'Suggestions appear once follow lists are imported and at least two profiles share a counterpart.',
          },
        }) ?? (
          <Rows
            columns="minmax(0,1fr) 74px minmax(0,1fr)"
            head={['ACCOUNT', ['FOLLOWED BY', 'right'], 'WHO FOLLOWS THEM']}
            rows={(suggestionsQuery.data?.suggestions ?? []).slice(0, 8).map((suggestion) => ({
              cells: [
                cell(`@${suggestion.username}`, { tone: 'var(--ink)' }),
                cell(`${suggestion.followed_by_count} of ${profiles.length}`, {
                  align: 'right',
                  tone: 'var(--accent)',
                }),
                cell(suggestion.followed_by.map((name) => `@${name}`).join(', '), {
                  font: 's',
                  size: '10px',
                  tone: 'var(--dim)',
                  wrap: true,
                }),
              ],
            }))}
          />
        )}
      </Panel>

      <Panel
        title="CONVERSATIONS"
        isNew
        src="member_comments.target_username"
        blurb="Comments whose target belongs to another member. Actual back-and-forth rather than a follow edge — the only two-way signal in the schema."
        caveat={`Export-only: comments live in the official data export and cannot be scraped. ${comments.length.toLocaleString()} comments held for @${subject}; ${resolvedComments.toLocaleString()} carry a URL that names the counterpart, and the rest are boxd.it short links this deployment cannot follow.`}
      >
        {panelState({
          isLoading: archiveQuery.isLoading,
          error: archiveQuery.error,
          isEmpty: conversations.length === 0,
          onRetry: () => archiveQuery.refetch(),
          errorTitle: 'The archive could not be loaded',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'No export-only data for this profile',
            body: 'Comments come from an official account export, not from public pages. No amount of scraping reaches them.',
            cta: { label: 'HOW TO SUPPLY AN EXPORT', href: sectionHref('data', 'profiles') },
          },
        }) ?? (
          <Rows
            columns="minmax(0,1.2fr) 52px 74px minmax(0,0.8fr)"
            head={['COUNTERPART', ['N', 'right'], ['LAST', 'right'], 'IN THE GROUP']}
            rows={conversations.slice(0, 8).map((entry) => ({
              cells: [
                cell(`@${subject} ↔ @${entry.username}`, { size: '10.5px' }),
                cell(String(entry.count), { align: 'right', tone: 'var(--accent)' }),
                cell(
                  entry.last
                    ? new Date(entry.last).toLocaleDateString('en-GB', {
                        month: 'short',
                        year: 'numeric',
                      })
                    : '—',
                  { align: 'right', size: '10px', tone: 'var(--muted)' },
                ),
                cell(entry.tracked ? 'tracked' : 'outside the group', {
                  font: 's',
                  size: '10px',
                  tone: entry.tracked ? 'var(--ok)' : 'var(--dim)',
                }),
              ],
            }))}
          />
        )}
      </Panel>

      <Panel
        title="WHERE THEY TALK"
        src="member_comments (export only)"
        blurb="The comments themselves, including the ones aimed outside the group. Where somebody talks is a social edge the follow graph does not contain."
      >
        {panelState({
          isLoading: archiveQuery.isLoading,
          error: archiveQuery.error,
          isEmpty: comments.length === 0,
          onRetry: () => archiveQuery.refetch(),
          errorTitle: 'The archive could not be loaded',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'No comments in the archive',
            body: 'Comments exist only in an official export. This profile has not supplied one.',
          },
        }) ?? (
          <Notes
            items={comments.slice(0, 4).map((comment) => ({
              label: `${
                counterpartFrom(comment.target_url)
                  ? `@${subject} → @${counterpartFrom(comment.target_url)}`
                  : 'Counterpart not resolvable from a boxd.it link'
              }${
                comment.commented_date
                  ? ` · ${new Date(comment.commented_date).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })}`
                  : ''
              }`,
              text: comment.comment_text
                ? comment.comment_text.slice(0, 320)
                : 'The export carried this comment with no body.',
            }))}
          />
        )}
      </Panel>
    </>
  );
}
