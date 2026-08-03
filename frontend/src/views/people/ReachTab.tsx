'use client';

import React from 'react';
import { useQuery } from '@tanstack/react-query';

import Panel from '../../components/terminal/Panel';
import Bars from '../../components/terminal/bodies/Bars';
import Posters from '../../components/terminal/bodies/Posters';
import Rows, { cell } from '../../components/terminal/bodies/Rows';
import { BarsSkeleton, panelState } from '../../components/terminal/states';
import { sectionHref } from '../../components/terminal/sections';
import { memberArchiveApi, peopleApi, profileApi, profileStatsApi } from '../../services/api';

/** The film a liked review is about, where the short link says so. */
function filmSlugFrom(url: string): string | null {
  const match = /letterboxd\.com\/[^/]+\/film\/([^/?#]+)/.exec(url);
  return match ? match[1] : null;
}

function authorFrom(url: string): string | null {
  const match = /letterboxd\.com\/([^/?#]+)\//.exec(url);
  if (!match) return null;
  const candidate = match[1].toLowerCase();
  if (['film', 'films', 'list', 'lists', 'journal', 'tag', 'search'].includes(candidate)) return null;
  return candidate;
}

export default function ReachTab({ subject, profiles }: { subject: string; profiles: string[] }) {
  const reachQuery = useQuery({
    queryKey: ['people-reach', profiles],
    queryFn: () => peopleApi.getReach(profiles),
    enabled: profiles.length > 0,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const statsQuery = useQuery({
    queryKey: ['profile-stats', subject],
    queryFn: () => profileStatsApi.getStats(subject),
    enabled: Boolean(subject),
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

  const cardQuery = useQuery({
    queryKey: ['people-member-card', subject],
    queryFn: () => peopleApi.getMemberCard(subject),
    enabled: Boolean(subject),
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const renameQuery = useQuery({
    queryKey: ['people-rename-resilience', profiles],
    queryFn: () => peopleApi.getRenameResilience(profiles),
    enabled: profiles.length > 0,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const analysisQuery = useQuery({
    queryKey: ['profile-analysis', subject],
    queryFn: () => profileApi.getAnalysis(subject),
    enabled: Boolean(subject),
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const mostLiked = statsQuery.data?.reviews.most_liked ?? [];
  const likedReviews = React.useMemo(
    () => archiveQuery.data?.liked_reviews ?? [],
    [archiveQuery.data],
  );
  const likedLists = archiveQuery.data?.liked_lists ?? [];
  const card = cardQuery.data;

  // Films they liked a review of and have no watch record for. Intent recorded
  // in a place nothing else looks.
  const watchedTitles = React.useMemo(
    () =>
      new Set(
        (analysisQuery.data?.recent_watching_trend ?? []).map((watch) =>
          watch.movie_title.toLowerCase(),
        ),
      ),
    [analysisQuery.data],
  );

  const likedUnseen = React.useMemo(() => {
    const bySlug = new Map<string, { slug: string; count: number; authors: Set<string> }>();
    likedReviews.forEach((like) => {
      const slug = filmSlugFrom(like.target_url);
      if (!slug) return;
      const entry = bySlug.get(slug) ?? { slug, count: 0, authors: new Set<string>() };
      entry.count += 1;
      const author = authorFrom(like.target_url);
      if (author) entry.authors.add(author);
      bySlug.set(slug, entry);
    });
    return Array.from(bySlug.values())
      .filter((entry) => !watchedTitles.has(entry.slug.replace(/-/g, ' ')))
      .sort((a, b) => b.count - a.count);
  }, [likedReviews, watchedTitles]);

  const resolvedLikes = likedReviews.filter((like) => filmSlugFrom(like.target_url)).length;

  return (
    <>
      <Panel
        title="FOLLOWERS AGAINST FOLLOWING"
        src="profiles.followers_count"
        blurb="Audience, not taste. A profile with a thousand followers behaves differently from one with forty, and it shows in the review-like numbers."
        caveat={reachQuery.data?.caveat}
      >
        {panelState({
          isLoading: reachQuery.isLoading,
          error: reachQuery.error,
          isEmpty: (reachQuery.data?.profiles ?? []).every((entry) => entry.followers === null),
          onRetry: () => reachQuery.refetch(),
          errorTitle: 'Audience figures could not be loaded',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'No profile headers read yet',
            body: 'Follower counts come from the profile header, which is read on its own schedule. Null is "never read", not zero.',
            cta: { label: 'SEE THE REFRESH LEDGER', href: sectionHref('data', 'refreshes') },
          },
          skeleton: <BarsSkeleton rows={5} />,
        }) ?? (
          <Bars
            items={(reachQuery.data?.profiles ?? []).map((entry) => ({
              name: `@${entry.username}`,
              weight: entry.followers ?? 0,
              value: entry.followers === null ? 'not read' : entry.followers.toLocaleString(),
              sub: entry.following === null ? '' : `follows ${entry.following.toLocaleString()}`,
            }))}
          />
        )}
      </Panel>

      <Panel
        title="WHICH REVIEWS ACTUALLY LANDED"
        src="reviews.likes_count"
        blurb="Their own writing, ranked by how it was received. A distribution rather than a total, because one viral review distorts every average."
        caveat="Like counts are read off the review page at sync time and only ever go up between reads. A review written since the last refresh has no count yet, not a count of zero."
      >
        {panelState({
          isLoading: statsQuery.isLoading,
          error: statsQuery.error,
          isEmpty: mostLiked.length === 0,
          onRetry: () => statsQuery.refetch(),
          errorTitle: 'Review reception could not be loaded',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'No liked reviews yet',
            body: 'Either nothing they wrote has been liked, or the review surface has not been read since they wrote it.',
          },
        }) ?? (
          <Rows
            columns="minmax(0,1fr) 58px 74px"
            head={['REVIEW', ['LIKES', 'right'], ['PUBLISHED', 'right']]}
            rows={mostLiked.slice(0, 8).map((review) => ({
              cells: [
                cell(review.year ? `${review.title} (${review.year})` : review.title, {
                  font: 's',
                  size: '10.5px',
                  wrap: true,
                }),
                cell(review.likes_count.toLocaleString(), {
                  align: 'right',
                  tone: 'var(--accent)',
                }),
                cell(
                  review.published_date
                    ? new Date(review.published_date).toLocaleDateString('en-GB', {
                        month: 'short',
                        year: 'numeric',
                      })
                    : '—',
                  { align: 'right', size: '10px', tone: 'var(--muted)' },
                ),
              ],
            }))}
          />
        )}
      </Panel>

      <Panel
        title="WHAT THEY ENDORSED"
        src="member_content_likes"
        blurb="Reviews and lists they liked. A read of somebody's attention that does not require them to have watched anything."
        caveat={`Export-only. ${likedReviews.length.toLocaleString()} liked reviews and ${likedLists.length.toLocaleString()} liked lists held for @${subject}.`}
      >
        {panelState({
          isLoading: archiveQuery.isLoading,
          error: archiveQuery.error,
          isEmpty: likedReviews.length + likedLists.length === 0,
          onRetry: () => archiveQuery.refetch(),
          errorTitle: 'The archive could not be loaded',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'No export-only data for this profile',
            body: 'Liked reviews and lists come from an official account export, not from public pages.',
            cta: { label: 'HOW TO SUPPLY AN EXPORT', href: sectionHref('data', 'profiles') },
          },
        }) ?? (
          <Rows
            columns="52px minmax(0,1fr) 78px"
            head={['KIND', 'WHAT', ['LIKED', 'right']]}
            rows={[
              ...likedReviews.slice(0, 6).map((like) => ({ kind: 'review', ...like })),
              ...likedLists.slice(0, 4).map((like) => ({ kind: 'list', ...like })),
            ].map((like) => ({
              cells: [
                cell(like.kind, { size: '9.5px', tone: 'var(--muted)' }),
                cell(
                  filmSlugFrom(like.target_url)?.replace(/-/g, ' ') ??
                    authorFrom(like.target_url)?.replace(/^/, '@') ??
                    like.target_url,
                  { font: 's', size: '10.5px', tone: 'var(--ink2)', wrap: true },
                ),
                cell(
                  like.liked_date
                    ? new Date(like.liked_date).toLocaleDateString('en-GB', {
                        month: 'short',
                        year: 'numeric',
                      })
                    : '—',
                  { align: 'right', size: '10px', tone: 'var(--muted)' },
                ),
              ],
            }))}
          />
        )}
      </Panel>

      <Panel
        title="LIKED BUT NEVER SEEN"
        isNew
        src="member_content_likes × profile_films"
        blurb="They liked a review of a film they have no watch record for. Intent, recorded in a place nobody looks — and a better watchlist than the watchlist."
        caveat={`Export-only, and only for likes whose short link has been resolved to a film: ${resolvedLikes.toLocaleString()} of ${likedReviews.length.toLocaleString()} liked reviews name one. A boxd.it link this deployment cannot follow stays out rather than being guessed at.`}
      >
        {panelState({
          isLoading: archiveQuery.isLoading || analysisQuery.isLoading,
          error: archiveQuery.error,
          isEmpty: likedUnseen.length === 0,
          onRetry: () => archiveQuery.refetch(),
          errorTitle: 'Liked-but-unseen could not be computed',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'Nothing liked that is also unseen',
            body: 'This needs an owner export with resolved like targets. Without one, there is no intent recorded anywhere to compare against the diary.',
            cta: { label: 'HOW TO SUPPLY AN EXPORT', href: sectionHref('data', 'profiles') },
          },
        }) ?? (
          <Posters
            items={likedUnseen.slice(0, 6).map((entry) => ({
              title: entry.slug.replace(/-/g, ' '),
              sub: `liked ${entry.count} review${entry.count === 1 ? '' : 's'}${
                entry.authors.size ? ` · ${Array.from(entry.authors).map((a) => `@${a}`).join(', ')}` : ''
              }`,
              right: String(entry.count),
              tone: 'var(--accent)',
              rightCaption: 'liked, unseen',
            }))}
          />
        )}
      </Panel>

      <Panel
        title="MEMBER CARD"
        src="profiles.member_badge · pronoun · location"
        caveat={card?.caveat}
      >
        {panelState({
          isLoading: cardQuery.isLoading,
          error: cardQuery.error,
          isEmpty: !card,
          onRetry: () => cardQuery.refetch(),
          errorTitle: 'The member card could not be loaded',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: { title: 'No profile metadata', body: 'Nothing has been read from the profile header yet.' },
        }) ?? (
          <Rows
            columns="96px minmax(0,1fr)"
            rows={(
              [
                ['Badge', card?.badge],
                ['Pronouns', card?.pronoun],
                ['Location', card?.location],
                ['First logged', card?.first_logged_date],
                ['Bio', card?.bio],
              ] as Array<[string, string | null | undefined]>
            )
              // A field the profile never supplied is absent, not an empty row
              // labelled "unknown" -- which reads as a fact we failed to fetch.
              .filter(([, value]) => Boolean(value))
              .map(([label, value]) => ({
                cells: [
                  cell(label, { size: '9.5px', tone: 'var(--muted)' }),
                  cell(String(value), { font: 's', size: '10.5px', tone: 'var(--ink2)', wrap: true }),
                ],
              }))}
          />
        )}
      </Panel>

      <Panel
        title="SURVIVES A RENAME"
        isNew
        src="profiles.letterboxd_person_id"
        blurb="The member id survives a username change, and the importer uses it to rename a profile in place instead of creating a second one."
        caveat={renameQuery.data?.caveat}
      >
        {panelState({
          isLoading: renameQuery.isLoading,
          error: renameQuery.error,
          isEmpty: (renameQuery.data?.profiles.length ?? 0) === 0,
          onRetry: () => renameQuery.refetch(),
          errorTitle: 'Rename resilience could not be read',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: { title: 'No profiles selected', body: 'Choose at least one profile above.' },
        }) ?? (
          <Rows
            columns="minmax(0,1fr) 110px minmax(0,1fr)"
            head={['PROFILE', ['MEMBER ID', 'right'], 'IF THEY RENAME']}
            rows={(renameQuery.data?.profiles ?? []).map((entry) => ({
              cells: [
                cell(`@${entry.username}`, { tone: 'var(--ink)' }),
                cell(entry.member_id === null ? 'not read' : String(entry.member_id), {
                  align: 'right',
                  size: '10px',
                  tone: entry.member_id === null ? 'var(--bad)' : 'var(--muted)',
                }),
                cell(
                  entry.survives_rename
                    ? 'Renamed in place, history kept'
                    : 'Would look like a new account',
                  {
                    font: 's',
                    size: '10px',
                    tone: entry.survives_rename ? 'var(--ok)' : 'var(--bad)',
                    wrap: true,
                  },
                ),
              ],
            }))}
          />
        )}
      </Panel>
    </>
  );
}
