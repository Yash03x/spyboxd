'use client';

import React, { useState } from 'react';
import { useUser } from '@clerk/nextjs';
import { useQuery } from '@tanstack/react-query';
import { motion, AnimatePresence } from 'framer-motion';
import { useRouter } from 'next/navigation';
import { profileApi, dashboardApi, changesApi } from '../services/api';
import { 
  ArrowPathIcon,
  PlusIcon,
  ChartBarIcon,
  FilmIcon
} from '@heroicons/react/24/outline';
import { 
  Users, 
  Film, 
  Star, 
  MessageCircle, 
  Activity,
  Award,
  Calendar,
  Radar,
  ArrowRight,
  Clock3,
} from 'lucide-react';
import LoadingSpinner from '../components/LoadingSpinner';
import ErrorMessage from '../components/ErrorMessage';
import StatsCard from '../components/Charts/StatsCard';
import ProfileCard from '../components/ProfileCard';
import RatingDistributionChart from '../components/Charts/RatingDistributionChart';
import ActivityChart from '../components/Charts/ActivityChart';
import RecentChangesCard from '../components/insights/RecentChangesCard';

const Dashboard: React.FC = () => {
  const [deletingProfile, setDeletingProfile] = useState<string | null>(null);
  const router = useRouter();
  const { user } = useUser();
  const isAdmin = Boolean(user?.publicMetadata?.is_admin);
  
  const { data: profiles, isLoading, error, refetch } = useQuery({
    queryKey: ['profiles'],
    queryFn: profileApi.getProfiles,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const { data: analytics, isLoading: analyticsLoading, refetch: refetchAnalytics } = useQuery({
    queryKey: ['dashboard-analytics'],
    queryFn: dashboardApi.getAnalytics,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const recentChangesQuery = useQuery({
    queryKey: ['recent-changes', 'latest-sync', 6],
    queryFn: () => changesApi.getRecentChanges({ limit: 6, latestSyncOnly: true }),
    staleTime: 2 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  // Handle profile deletion
  const handleDeleteProfile = async (username: string) => {
    if (window.confirm(`Are you sure you want to delete ${username}? This cannot be undone.`)) {
      setDeletingProfile(username);
      try {
        await profileApi.deleteProfile(username);
        await Promise.all([refetch(), refetchAnalytics()]);
      } catch (error) {
        console.error('Failed to delete profile:', error);
      } finally {
        setDeletingProfile(null);
      }
    }
  };

  // Handle manual refresh all
  const handleRefreshAll = () => {
    void Promise.all([refetch(), refetchAnalytics(), recentChangesQuery.refetch()]);
  };

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message="Failed to load profiles" />;

  // Ensure profiles is an array
  const profilesArray = Array.isArray(profiles) ? profiles : [];

  // Data from analytics query is now the single source of truth for dashboard stats
  const totalProfiles = analytics?.system_stats?.total_profiles ?? 0;
  const totalMovies = analytics?.system_stats?.total_movies_tracked ?? 0;
  const totalReviews = analytics?.system_stats?.total_reviews ?? 0;
  const avgRating = analytics?.system_stats?.global_avg_rating ?? 0;

  // Calculate completion rate based on profile statuses
  const activeProfiles = profilesArray.filter(p => p.scraping_status === 'completed').length;
  const latestSyncTimestamp = Math.max(
    ...profilesArray
      .filter((profile) => profile.last_scraped_at)
      .map((profile) => new Date(profile.last_scraped_at!).getTime()),
    0,
  );
  
  // Use analytics data directly
  const aggregateRatingDistribution = analytics?.rating_distribution ?? {};
  const aggregateActivityData = analytics?.activity_data ?? [];
  const signalSummary = analytics?.group_signals?.summary;
  const strongestPair = signalSummary?.strongest_alignment_pair;

  if (analyticsLoading) {
    return <LoadingSpinner message="Loading dashboard analytics..." />;
  }

  return (
    <motion.div 
      className="space-y-8"
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.6 }}
    >
      {/* Header with Actions */}
      <motion.div 
        className="flex items-center justify-between"
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
      >
        <div>
          <h1 className="text-4xl font-bold text-white text-glow mb-2">
            Dashboard
          </h1>
          <p className="text-white/60">
            Analytics over the latest shared Letterboxd dataset
          </p>
        </div>
        
        <motion.div 
          className="flex space-x-4"
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: 0.3 }}
        >
          <motion.button 
            onClick={handleRefreshAll}
            className="btn-secondary flex items-center space-x-2"
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
          >
            <ArrowPathIcon className="w-5 h-5" />
            <span>Refresh All</span>
          </motion.button>
          
          <motion.button
            onClick={() => router.push('/profiles')}
            className="btn-primary flex items-center space-x-2"
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
          >
            <PlusIcon className="w-5 h-5" />
            <span>{isAdmin ? 'Manage Profiles' : 'Browse Profiles'}</span>
          </motion.button>
        </motion.div>
      </motion.div>

      {/* System Overview Stats */}
      <motion.div 
        className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.4 }}
      >
        <StatsCard
          title="Total Profiles"
          value={totalProfiles}
          subtitle="Active community members"
          icon={Users}
          delay={0}
        />
        
        <StatsCard
          title="Movies Tracked"
          value={totalMovies}
          subtitle="Across all profiles"
          icon={Film}
          gradient="from-blue-500/20 to-blue-600/10"
          delay={0.1}
        />
        
        <StatsCard
          title="Total Reviews"
          value={totalReviews}
          subtitle="Community insights"
          icon={MessageCircle}
          gradient="from-purple-500/20 to-purple-600/10"
          delay={0.2}
        />
        
        <StatsCard
          title="Average Rating"
          value={avgRating.toFixed(1)}
          subtitle={`${activeProfiles} profiles completed`}
          icon={Star}
          gradient="from-yellow-500/20 to-yellow-600/10"
          delay={0.3}
        />
      </motion.div>

      {/* Charts Section */}
      <motion.div 
        className="grid grid-cols-1 xl:grid-cols-2 gap-8"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.6 }}
      >
        <RatingDistributionChart 
          data={aggregateRatingDistribution} 
          globalAverage={avgRating}
        />
        <ActivityChart data={aggregateActivityData} />
      </motion.div>

      {/* Additional Metrics Row */}
      <motion.div 
        className="grid grid-cols-1 md:grid-cols-3 gap-6"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.8 }}
      >
        <StatsCard
          title="Pending Syncs"
          value={profilesArray.filter(p => p.scraping_status !== 'completed').length}
          subtitle="Profiles awaiting a local upload"
          icon={Activity}
          gradient="from-green-500/20 to-green-600/10"
          delay={0}
        />
        
        <StatsCard
          title="Top Reviewer"
          value={profilesArray.length > 0 ? 
            profilesArray.reduce((prev, current) => 
              (current.total_reviews || 0) > (prev.total_reviews || 0) ? current : prev
            ).username : 'N/A'
          }
          subtitle="Most active reviewer"
          icon={Award}
          gradient="from-pink-500/20 to-pink-600/10"
          delay={0.1}
        />
        
        <StatsCard
          title="Last Update"
          value={latestSyncTimestamp > 0 ? new Date(latestSyncTimestamp).toLocaleDateString() : 'Never'}
          subtitle="Most recent data sync"
          icon={Calendar}
          gradient="from-indigo-500/20 to-indigo-600/10"
          delay={0.2}
        />
      </motion.div>

      {/* Compact entry point for the dedicated investigation workspace */}
      <motion.section
        className="card-cinema overflow-hidden"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.9 }}
      >
        <div className="flex flex-col gap-6 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex items-start gap-4">
            <div className="rounded-2xl border border-cinema-400/30 bg-cinema-500/15 p-3 text-cinema-300">
              <Radar className="h-7 w-7" />
            </div>
            <div>
              <h2 className="text-2xl font-bold text-white">Spy Signals</h2>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-white/60">
                Find who watched the same film on the same day, within a one-day gap,
                or across a custom set of profiles.
              </p>
              {strongestPair && (
                <p className="mt-3 text-sm text-cinema-300">
                  Strongest current pair: {strongestPair.profiles.join(' + ')}
                </p>
              )}
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3 xl:min-w-[420px]">
            <div className="rounded-xl border border-white/10 bg-black/15 px-4 py-3">
              <p className="text-2xl font-bold text-white">{signalSummary?.same_day_events ?? 0}</p>
              <p className="mt-1 text-xs text-white/50">Same-day alerts</p>
            </div>
            <div className="rounded-xl border border-white/10 bg-black/15 px-4 py-3">
              <div className="flex items-center gap-2">
                <Clock3 className="h-4 w-4 text-cinema-300" />
                <p className="text-2xl font-bold text-white">{signalSummary?.one_day_gap_events ?? 0}</p>
              </div>
              <p className="mt-1 text-xs text-white/50">1-day echoes</p>
            </div>
            <div className="rounded-xl border border-white/10 bg-black/15 px-4 py-3">
              <p className="text-2xl font-bold text-white">{signalSummary?.shared_titles ?? 0}</p>
              <p className="mt-1 text-xs text-white/50">Shared titles</p>
            </div>
          </div>

          <motion.button
            type="button"
            onClick={() => router.push('/spy-signals')}
            className="btn-primary flex shrink-0 items-center justify-center gap-2"
            whileHover={{ scale: 1.03 }}
            whileTap={{ scale: 0.97 }}
          >
            Open Spy Signals
            <ArrowRight className="h-5 w-5" />
          </motion.button>
        </div>
        <RecentChangesCard
          data={recentChangesQuery.data}
          loading={recentChangesQuery.isLoading}
          error={Boolean(recentChangesQuery.error)}
          onRetry={() => void recentChangesQuery.refetch()}
        />
      </motion.section>

      {/* Profiles Grid */}
      <motion.div 
        className="space-y-6"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 1.05 }}
      >
        <div className="flex items-center justify-between">
          <h2 className="text-2xl font-bold text-white">
            Community Profiles
          </h2>
          <span className="text-white/60 text-sm">
            {profilesArray.length} {profilesArray.length === 1 ? 'profile' : 'profiles'} loaded
          </span>
        </div>

        <AnimatePresence mode="popLayout">
          {profilesArray.length > 0 ? (
            <motion.div 
              className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6"
              layout
            >
              {profilesArray.map((profile, index) => (
                <ProfileCard
                  key={profile.username}
                  profile={profile}
                  index={index}
                  onDelete={isAdmin ? handleDeleteProfile : undefined}
                  isDeleting={deletingProfile === profile.username}
                />
              ))}
            </motion.div>
          ) : (
            <motion.div 
              className="card-cinema text-center py-16"
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: 0.3 }}
            >
              <motion.div 
                className="w-24 h-24 bg-cinema-500/20 rounded-full flex items-center justify-center mb-6 mx-auto"
                animate={{ 
                  scale: [1, 1.05, 1],
                  boxShadow: [
                    "0 0 20px rgba(229, 81, 0, 0.3)",
                    "0 0 40px rgba(229, 81, 0, 0.5)",
                    "0 0 20px rgba(229, 81, 0, 0.3)"
                  ]
                }}
                transition={{ duration: 2, repeat: Infinity }}
              >
                <FilmIcon className="w-12 h-12 text-cinema-400" />
              </motion.div>
              
              <h3 className="text-xl font-bold text-white mb-3">
                No profiles loaded yet
              </h3>
              <p className="text-white/60 mb-8 max-w-md mx-auto">
                Start building your Letterboxd community by adding profiles for analysis and tracking.
              </p>
              
              <div className="flex justify-center space-x-4">
                <motion.button
                  onClick={() => router.push('/profiles')}
                  className="btn-primary flex items-center space-x-2"
                  whileHover={{ scale: 1.05 }}
                  whileTap={{ scale: 0.95 }}
                >
                  <PlusIcon className="w-5 h-5" />
                  <span>{isAdmin ? 'Manage Profiles' : 'Browse Profiles'}</span>
                </motion.button>
                
                <motion.button 
                  className="btn-secondary flex items-center space-x-2"
                  whileHover={{ scale: 1.05 }}
                  whileTap={{ scale: 0.95 }}
                >
                  <ChartBarIcon className="w-5 h-5" />
                  <span>View Analytics</span>
                </motion.button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>
    </motion.div>
  );
};

export default Dashboard;
