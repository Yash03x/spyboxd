'use client';

import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { profileApi } from '../../../services/api';
import LoadingSpinner from '../../../components/LoadingSpinner';
import ErrorMessage from '../../../components/ErrorMessage';

export default function ProfileSnapshotPage() {
  const params = useParams<{ username: string }>();
  const username = params.username;
  const profileQuery = useQuery({
    queryKey: ['profile-snapshot', username],
    queryFn: () => profileApi.getProfileSnapshot(username),
    enabled: Boolean(username),
  });

  if (profileQuery.isLoading) return <LoadingSpinner message="Loading profile…" />;
  if (profileQuery.error || !profileQuery.data) {
    return <ErrorMessage message="This profile is unavailable or you do not have access." />;
  }
  const profile = profileQuery.data;

  return (
    <main className="min-h-screen flex items-center justify-center px-4 py-12">
      <div className="w-full max-w-xl rounded-2xl bg-black/30 backdrop-blur-xl border border-white/10 p-8 space-y-6">
        <div className="text-center space-y-3">
          {profile.profile_image_url && (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={profile.profile_image_url}
              alt={profile.username}
              className="w-20 h-20 rounded-full mx-auto object-cover border-2 border-cinema-500/40"
            />
          )}
          <h1 className="text-2xl font-bold text-white">{profile.username}</h1>
          {profile.location && <p className="text-sm text-white/50">{profile.location}</p>}
          {profile.bio && <p className="text-sm text-white/70 max-w-sm mx-auto">{profile.bio}</p>}
        </div>

        <div className="grid grid-cols-3 gap-4 text-center">
          {[
            { label: 'Films', value: profile.total_films?.toLocaleString() ?? '—' },
            { label: 'Avg Rating', value: profile.avg_rating ? `${profile.avg_rating.toFixed(1)}★` : '—' },
            { label: 'Reviews', value: profile.total_reviews?.toLocaleString() ?? '—' },
          ].map(({ label, value }) => (
            <div key={label} className="rounded-xl bg-white/5 border border-white/10 p-4">
              <div className="text-2xl font-bold text-cinema-400">{value}</div>
              <div className="text-xs text-white/50 mt-1">{label}</div>
            </div>
          ))}
        </div>

        <p className="text-center text-xs text-white/30">
          Back to{' '}
          <Link href="/dashboard" className="text-cinema-400 font-medium hover:text-cinema-300 transition-colors">
            My Dashboard
          </Link>
        </p>
      </div>
    </main>
  );
}
