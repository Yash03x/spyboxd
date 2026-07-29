import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';

const API_URL = process.env.API_URL ?? 'http://localhost:8000';

interface Props {
  params: Promise<{ username: string }>;
}

async function getPublicProfile(username: string) {
  try {
    const res = await fetch(
      `${API_URL}/public/profile/${encodeURIComponent(username)}`,
      { next: { revalidate: 3600 } }
    );
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { username } = await params;
  const profile = await getPublicProfile(username);

  if (!profile) {
    return { title: `${username} — Spyboxd` };
  }

  const description = `${profile.total_films} films watched · ${profile.avg_rating?.toFixed(1)}★ avg · ${profile.total_reviews} reviews`;

  return {
    title: `${profile.username} on Spyboxd`,
    description,
    openGraph: {
      title: `${profile.username} on Spyboxd`,
      description,
    },
  };
}

export default async function PublicProfilePage({ params }: Props) {
  const { username } = await params;
  const profile = await getPublicProfile(username);

  if (!profile) notFound();

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
          Powered by{' '}
          <Link href="/" className="text-cinema-400 font-medium hover:text-cinema-300 transition-colors">
            Spyboxd
          </Link>
        </p>
      </div>
    </main>
  );
}
