'use client';

import { SignOutButton, UserButton, useAuth } from '@clerk/nextjs';
import { useQuery } from '@tanstack/react-query';
import { motion } from 'framer-motion';
import Image from 'next/image';
import Link from 'next/link';
import type { ReactNode } from 'react';
import { Activity, CalendarClock, Film, MessageCircle, Radar, Star, Users } from 'lucide-react';
import ActivityChart from '../components/Charts/ActivityChart';
import RatingDistributionChart from '../components/Charts/RatingDistributionChart';
import StatsCard from '../components/Charts/StatsCard';
import ErrorMessage from '../components/ErrorMessage';
import LoadingSpinner from '../components/LoadingSpinner';
import { publicDashboardApi } from '../services/api';

export default function PublicDashboard() {
  const { isSignedIn } = useAuth();
  const dashboardQuery = useQuery({
    queryKey: ['public-dashboard-analytics'],
    queryFn: publicDashboardApi.getAnalytics,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const renderShell = (content: ReactNode) => (
    <main className="min-h-screen px-4 py-6 sm:px-8 lg:px-12" data-testid="public-dashboard">
      <div className="mx-auto max-w-7xl space-y-8">
        <PublicHeader isSignedIn={isSignedIn} />
        {content}
      </div>
    </main>
  );

  if (dashboardQuery.isLoading) return renderShell(<LoadingSpinner message="Loading Spyboxd totals…" />);
  if (dashboardQuery.error || !dashboardQuery.data) {
    return renderShell(<ErrorMessage message="The public dashboard could not be loaded." />);
  }

  const analytics = dashboardQuery.data;
  const stats = analytics.system_stats;
  const signals = analytics.signal_counts;
  const lastSync = analytics.data_health.last_synced_at
    ? new Date(analytics.data_health.last_synced_at).toLocaleDateString()
    : 'Not yet';

  return renderShell(
    <>
      <motion.section
        className="space-y-3 py-4"
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <p className="text-sm font-semibold uppercase tracking-[0.2em] text-cinema-300">Public dashboard</p>
        <h1 className="max-w-4xl text-4xl font-bold leading-tight text-white text-glow sm:text-5xl">
          Movie activity at a glance, without exposing anyone&apos;s profile.
        </h1>
        <p className="max-w-3xl text-base leading-7 text-white/60">
          These are database-wide totals and anonymous distributions. Sign in to choose the profiles you monitor, compare people, and investigate same-day watches.
        </p>
      </motion.section>

      <section className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-4" aria-label="Aggregate totals">
        <StatsCard title="Profiles analyzed" value={stats.total_profiles} subtitle={`${analytics.data_health.completed_profiles} ready for analysis`} icon={Users} />
        <StatsCard title="Unique films" value={stats.total_movies_tracked} subtitle="Across the aggregate dataset" icon={Film} gradient="from-blue-500/20 to-blue-600/10" delay={0.05} />
        <StatsCard title="Reviews" value={stats.total_reviews} subtitle="Imported review records" icon={MessageCircle} gradient="from-purple-500/20 to-purple-600/10" delay={0.1} />
        <StatsCard title="Average rating" value={stats.global_avg_rating.toFixed(1)} subtitle="Across rated entries" icon={Star} gradient="from-yellow-500/20 to-yellow-600/10" delay={0.15} />
      </section>

      <section className="grid grid-cols-1 gap-8 xl:grid-cols-2" aria-label="Aggregate charts">
        <RatingDistributionChart data={analytics.rating_distribution} globalAverage={stats.global_avg_rating} />
        <ActivityChart data={analytics.activity_data} />
      </section>

      <section className="card-cinema overflow-hidden" aria-labelledby="anonymous-signals-title">
        <div className="flex items-start gap-4">
          <span className="rounded-2xl border border-cinema-400/30 bg-cinema-500/15 p-3 text-cinema-300"><Radar className="h-7 w-7" /></span>
          <div>
            <h2 id="anonymous-signals-title" className="text-2xl font-bold text-white">Anonymous spy-signal totals</h2>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-white/55">Counts show how much overlap exists in the dataset. Names, profile pairs, titles, ratings, and watch dates stay inside the signed-in workspace.</p>
          </div>
        </div>
        <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <AggregateSignal icon={Activity} label="Same-day events" value={signals.same_day_events} />
          <AggregateSignal icon={CalendarClock} label="One-day echoes" value={signals.one_day_gap_events} />
          <AggregateSignal icon={Film} label="Shared titles" value={signals.shared_titles} />
          <AggregateSignal icon={Users} label="Profiles with dates" value={signals.profiles_with_diary_dates} />
        </div>
        <div className="mt-6 flex flex-col gap-4 border-t border-white/10 pt-6 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-white/45">Latest completed profile sync: <span className="font-medium text-white/70">{lastSync}</span></p>
          <Link href={isSignedIn ? '/profiles' : '/sign-in?redirect_url=%2Fprofiles'} className="btn-secondary text-center">
            {isSignedIn ? 'Choose monitored profiles' : 'Sign in for private tools'}
          </Link>
        </div>
      </section>
    </>
  );
}

function PublicHeader({ isSignedIn }: { isSignedIn: boolean | undefined }) {
  return (
    <header className="flex flex-col gap-5 border-b border-white/10 pb-6 sm:flex-row sm:items-center sm:justify-between">
      <Link href="/" className="flex items-center gap-3" aria-label="Spyboxd public dashboard">
        <Image
          src="/icon.svg"
          alt=""
          width={44}
          height={44}
          className="h-11 w-11 rounded-xl border border-cinema-400/20 shadow-glow"
          priority
        />
        <span>
          <span className="block text-xl font-bold text-white">Spyboxd</span>
          <span className="block text-xs text-white/45">Aggregate Letterboxd signals</span>
        </span>
      </Link>
      <div className="flex flex-wrap items-center gap-3">
        {isSignedIn ? (
          <>
            <Link href="/dashboard" className="btn-primary whitespace-nowrap">Open My Dashboard</Link>
            <SignOutButton redirectUrl="/">
              <button type="button" className="btn-secondary whitespace-nowrap">Sign out</button>
            </SignOutButton>
            <UserButton />
          </>
        ) : (
          <Link href="/sign-in?redirect_url=%2Fprofiles" className="btn-primary whitespace-nowrap">Sign in to monitor profiles</Link>
        )}
      </div>
    </header>
  );
}

function AggregateSignal({ icon: Icon, label, value }: { icon: typeof Activity; label: string; value: number }) {
  return (
    <div className="rounded-xl border border-white/10 bg-black/15 p-4">
      <Icon className="h-5 w-5 text-cinema-300" />
      <p className="mt-3 text-2xl font-bold text-white">{value.toLocaleString()}</p>
      <p className="mt-1 text-xs text-white/50">{label}</p>
    </div>
  );
}
