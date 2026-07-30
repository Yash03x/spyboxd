'use client';

import React, { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { motion } from 'framer-motion';
import { useQuery } from '@tanstack/react-query';
import { Calendar, MessageCircle, Star, Ticket } from 'lucide-react';

import LoadingSpinner from '../components/LoadingSpinner';
import ErrorMessage from '../components/ErrorMessage';
import ActivityChart from '../components/Charts/ActivityChart';
import RatingDistributionChart from '../components/Charts/RatingDistributionChart';
import StatsCard from '../components/Charts/StatsCard';
import SpoilerReviewText from '../components/SpoilerReviewText';
import { profileApi } from '../services/api';

function formatMovieTitle(title: string, year: number | null): string {
  return year ? `${title} (${year})` : title;
}

function formatDate(value: string | null | undefined): string {
  if (!value) {
    return 'Unknown';
  }
  return new Date(value).toLocaleDateString();
}

const Analysis: React.FC = () => {
  const [selectedProfile, setSelectedProfile] = useState('');

  const { data: profiles, isLoading: loadingProfiles, error: profilesError } = useQuery({
    queryKey: ['profiles'],
    queryFn: profileApi.getProfiles,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const profilesArray = useMemo(() => (Array.isArray(profiles) ? profiles : []), [profiles]);

  useEffect(() => {
    if (!selectedProfile && profilesArray.length > 0) {
      setSelectedProfile(profilesArray[0].username);
    }
  }, [profilesArray, selectedProfile]);

  const {
    data: analysis,
    isLoading: loadingAnalysis,
    error: analysisError,
  } = useQuery({
    queryKey: ['analysis', selectedProfile],
    queryFn: () => profileApi.getAnalysis(selectedProfile),
    enabled: Boolean(selectedProfile),
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const coverageLimitations = analysis?.data_coverage?.limitations?.filter(
    (item) => item.trim().length > 0,
  ) ?? [];
  const hasCoverageLimitations = coverageLimitations.length > 0;

  if (loadingProfiles) {
    return <LoadingSpinner message="Loading profiles..." />;
  }

  if (profilesError) {
    return <ErrorMessage message="Failed to load profiles." />;
  }

  return (
    <motion.div
      className="space-y-8"
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.6 }}
    >
      <div>
        <h1 className="text-4xl font-bold text-white text-glow mb-2">Analysis</h1>
        <p className="text-white/60">
          Single-profile deep dives over the profiles you track.
        </p>
      </div>

      {profilesArray.length === 0 ? (
        <section className="card-cinema flex min-h-72 flex-col items-center justify-center px-6 text-center">
          <Ticket className="h-10 w-10 text-cinema-400" />
          <h2 className="mt-5 text-xl font-semibold text-white">Track a profile to start</h2>
          <p className="mt-2 max-w-md text-sm leading-6 text-white/55">
            Add an existing Letterboxd profile or request a new one in My Profiles, then return for its ratings, diary activity, and reviews.
          </p>
          <Link href="/profiles" className="btn-primary mt-5">Open My Profiles</Link>
        </section>
      ) : (
      <motion.div
        className="card-cinema"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
      >
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h2 className="text-xl font-semibold text-white">Select Profile</h2>
            <p className="mt-1 text-sm text-white/60">
              Choose any synced profile to inspect ratings, diary activity, and recent reviews.
            </p>
          </div>
          <div className="w-full lg:w-96">
            <select
              value={selectedProfile}
              onChange={(event) => setSelectedProfile(event.target.value)}
              className="input-field w-full"
            >
              {profilesArray.length === 0 && <option value="">No profiles available</option>}
              {profilesArray.map((profile) => (
                <option key={profile.username} value={profile.username}>
                  {profile.username}
                </option>
              ))}
            </select>
          </div>
        </div>
      </motion.div>
      )}

      {selectedProfile && loadingAnalysis && (
        <LoadingSpinner message={`Loading analysis for @${selectedProfile}...`} />
      )}

      {analysisError && (
        <ErrorMessage message="Failed to load profile analysis." />
      )}

      {analysis && (
        <>
          <div className="grid grid-cols-1 gap-6 md:grid-cols-2 xl:grid-cols-4">
            <StatsCard
              title="Films Tracked"
              value={analysis.total_films}
              subtitle={`${analysis.rated_films} rated / ${analysis.liked_films} liked`}
              icon={Ticket}
              delay={0}
            />
            <StatsCard
              title="Average Rating"
              value={analysis.avg_rating.toFixed(1)}
              subtitle={`Last synced ${formatDate(analysis.last_scraped_at)}`}
              icon={Star}
              gradient="from-yellow-500/20 to-yellow-600/10"
              delay={0.1}
            />
            <StatsCard
              title="Reviews"
              value={analysis.total_reviews}
              subtitle={analysis.join_date ? `Member since ${new Date(analysis.join_date).getFullYear()}` : 'Join date unavailable'}
              icon={MessageCircle}
              gradient="from-pink-500/20 to-pink-600/10"
              delay={0.2}
            />
            <StatsCard
              title="Coverage"
              value={analysis.data_coverage?.stats_label ?? 'Unknown'}
              subtitle={analysis.data_coverage?.summary ?? 'No coverage metadata available'}
              icon={Calendar}
              gradient="from-blue-500/20 to-blue-600/10"
              delay={0.3}
            />
          </div>

          <div className="grid grid-cols-1 gap-8 xl:grid-cols-2">
            <RatingDistributionChart
              data={analysis.rating_distribution}
              title={`Rating Distribution for @${analysis.username}`}
              globalAverage={analysis.avg_rating}
            />
            <ActivityChart
              data={analysis.monthly_stats}
              title={`Diary Activity for @${analysis.username}`}
            />
          </div>

          <div className={`grid grid-cols-1 items-start gap-6 ${hasCoverageLimitations ? 'xl:grid-cols-3' : ''}`}>
            <motion.div
              className={`analysis-panel ${hasCoverageLimitations ? 'xl:col-span-2' : ''}`}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.2 }}
            >
              <h2 className="text-xl font-semibold text-white">Recent Watches</h2>
              <p className="mt-1 text-sm text-white/60">
                Latest diary-visible films and ratings in the current imported dataset.
              </p>

              <div className="mt-5 space-y-3">
                {analysis.recent_watching_trend.length > 0 ? (
                  analysis.recent_watching_trend.map((entry) => (
                    <div
                      key={`${entry.movie_title}-${entry.movie_year ?? 'na'}-${entry.watched_date ?? 'na'}`}
                      className="rounded-2xl border border-white/10 bg-white/5 p-4"
                    >
                      <div className="flex items-start justify-between gap-4">
                        <div>
                          <p className="font-medium text-white">
                            {formatMovieTitle(entry.movie_title, entry.movie_year)}
                          </p>
                          <p className="mt-1 text-xs text-white/60">
                            Watched {formatDate(entry.watched_date)}
                            {entry.is_rewatch ? ' / Rewatch' : ''}
                          </p>
                        </div>
                        <div className="rounded-lg border border-cinema-400/20 bg-cinema-500/10 px-3 py-1 text-xs font-medium text-cinema-300">
                          {entry.rating !== null ? `${entry.rating.toFixed(1)} stars` : 'Unrated'}
                        </div>
                      </div>
                    </div>
                  ))
                ) : (
                  <p className="mt-5 text-sm text-white/50">No watched-date entries available.</p>
                )}
              </div>
            </motion.div>

            {hasCoverageLimitations ? (
              <motion.div
                className="analysis-panel"
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.25 }}
              >
                <h2 className="text-xl font-semibold text-white">Coverage Notes</h2>
                <p className="mt-1 text-sm text-white/60">
                  This profile’s current import quality and missing surfaces.
                </p>

                <div className="mt-5 rounded-2xl border border-white/10 bg-white/5 p-4">
                  <p className="text-sm text-white/80">
                    {analysis.data_coverage?.summary ?? 'Coverage limitations apply to this profile.'}
                  </p>
                  <ul className="mt-4 space-y-2 text-sm text-white/55">
                    {coverageLimitations.map((item) => (
                      <li key={item}>- {item}</li>
                    ))}
                  </ul>
                </div>
              </motion.div>
            ) : null}
          </div>

          <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-2">
            <motion.div
              className="analysis-panel"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.3 }}
            >
              <h2 className="text-xl font-semibold text-white">Recent Ratings</h2>
              <div className="mt-5 space-y-3">
                {analysis.recent_ratings.length > 0 ? (
                  analysis.recent_ratings.map((entry) => (
                    <div
                      key={`${entry.movie_title}-${entry.movie_year ?? 'na'}-${entry.watched_date ?? 'na'}-rating`}
                      className="rounded-2xl border border-white/10 bg-white/5 p-4"
                    >
                      <div className="flex items-start justify-between gap-4">
                        <div>
                          <p className="font-medium text-white">
                            {formatMovieTitle(entry.movie_title, entry.movie_year)}
                          </p>
                          <p className="mt-1 text-xs text-white/60">
                            {entry.watched_date ? `Watched ${formatDate(entry.watched_date)}` : 'No watch date'}
                          </p>
                        </div>
                        <div className="rounded-lg border border-cinema-400/20 bg-cinema-500/10 px-3 py-1 text-xs font-medium text-cinema-300">
                          {entry.rating !== null ? `${entry.rating.toFixed(1)} stars` : 'Unrated'}
                        </div>
                      </div>
                    </div>
                  ))
                ) : (
                  <p className="text-sm text-white/50">No rating entries available.</p>
                )}
              </div>
            </motion.div>

            <motion.div
              className="analysis-panel"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.35 }}
            >
              <h2 className="text-xl font-semibold text-white">Recent Reviews</h2>
              <div className="mt-5 space-y-3">
                {analysis.recent_reviews.length > 0 ? (
                  analysis.recent_reviews.map((review) => {
                    const reviewText = review.review_text?.trim();
                    const movieLabel = formatMovieTitle(review.movie_title, review.movie_year);
                    return (
                      <div
                        key={`${analysis.username}-${review.movie_title}-${review.movie_year ?? 'na'}-${review.published_date ?? 'na'}`}
                        className="rounded-2xl border border-white/10 bg-white/5 p-4"
                      >
                        <div className="flex items-start justify-between gap-4">
                          <div>
                            <p className="font-medium text-white">{movieLabel}</p>
                            <p className="mt-1 text-xs text-white/60">
                              Published {formatDate(review.published_date)}
                            </p>
                          </div>
                          <div className="rounded-lg border border-cinema-400/20 bg-cinema-500/10 px-3 py-1 text-xs font-medium text-cinema-300">
                            {review.rating !== null ? `${review.rating.toFixed(1)} stars` : 'No rating'}
                          </div>
                        </div>
                        {reviewText ? (
                          <div className="mt-3">
                            <SpoilerReviewText
                              text={reviewText}
                              containsSpoilers={review.contains_spoilers}
                              reviewLabel={movieLabel}
                              className="text-sm leading-6 text-white/70"
                            />
                          </div>
                        ) : null}
                      </div>
                    );
                  })
                ) : (
                  <p className="text-sm text-white/50">No reviews available.</p>
                )}
              </div>
            </motion.div>
          </div>
        </>
      )}
    </motion.div>
  );
};

export default Analysis;
