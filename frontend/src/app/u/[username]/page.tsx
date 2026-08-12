'use client';

import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';

import Panel from '../../../components/terminal/Panel';
import Notes from '../../../components/terminal/bodies/Notes';
import { panelState } from '../../../components/terminal/states';
import { profileApi } from '../../../services/api';

/**
 * A single profile's shareable snapshot: one terminal panel on an otherwise
 * empty page. Signed-in only -- middleware bounces anonymous visitors, and the
 * production canary counts on that.
 */
export default function ProfileSnapshotPage() {
  const params = useParams<{ username: string }>();
  const username = params.username;
  const profileQuery = useQuery({
    queryKey: ['profile-snapshot', username],
    queryFn: () => profileApi.getProfileSnapshot(username),
    enabled: Boolean(username),
  });

  const profile = profileQuery.data;

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-[40rem] flex-col justify-center px-4 py-12">
      <Panel
        title={profile ? `@${profile.username}` : 'PROFILE SNAPSHOT'}
        src="profiles · public snapshot"
        stats={
          profile
            ? [
                { big: profile.total_films?.toLocaleString() ?? '—', unit: 'FILMS' },
                {
                  big: profile.avg_rating ? profile.avg_rating.toFixed(1) : '—',
                  unit: 'AVG RATING',
                  tone: 'var(--accent)',
                },
                { big: profile.total_reviews?.toLocaleString() ?? '—', unit: 'REVIEWS' },
              ]
            : undefined
        }
        caveat={
          <>
            The full picture lives in <Link href={`/people?tab=one&subject=${encodeURIComponent(username ?? '')}`}>People › One person</Link>.
          </>
        }
      >
        {panelState({
          isLoading: profileQuery.isLoading,
          error: profileQuery.error,
          isEmpty: !profileQuery.isLoading && !profileQuery.error && !profile,
          severity: 'fatal',
          onRetry: () => profileQuery.refetch(),
          errorTitle: 'This profile is unavailable',
          errorBody: 'It may not exist here, or this login has no access to it.',
          empty: {
            title: 'This profile is unavailable',
            body: 'It may not exist here, or this login has no access to it.',
          },
        }) ??
          (profile ? (
            <Notes
              items={[
                {
                  label: profile.display_name || `@${profile.username}`,
                  text:
                    [profile.location, profile.bio].filter(Boolean).join(' — ') ||
                    'No public bio on the profile.',
                },
                {
                  label: 'Opinion coverage',
                  text: `${profile.rated_films.toLocaleString()} rated · ${profile.liked_films.toLocaleString()} liked`,
                },
              ]}
            />
          ) : null)}
      </Panel>
    </main>
  );
}
