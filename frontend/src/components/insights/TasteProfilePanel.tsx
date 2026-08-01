'use client';

import React, { useMemo } from 'react';
import { motion } from 'framer-motion';
import { useQuery } from '@tanstack/react-query';
import { Dna } from 'lucide-react';

import { insightsApi } from '../../services/api';
import type { TasteTrait } from '../../services/api';

const DIMENSION_LABELS: Record<string, string> = {
  genre: 'Genres',
  director: 'Directors',
  actor: 'Actors',
  language: 'Languages',
  country: 'Countries',
  decade: 'Decades',
  keyword: 'Themes',
  runtime: 'Runtime',
};

/**
 * The taste breakdown for a single profile. The comparison view answers "where
 * do two people agree"; this answers "what does this person actually gravitate
 * toward", which only needs one profile's ratings.
 */
const TasteProfilePanel: React.FC<{ username: string; delay?: number }> = ({
  username,
  delay = 0,
}) => {
  const tasteQuery = useQuery({
    queryKey: ['taste-dna', 'single', username],
    queryFn: () => insightsApi.getTasteDna([username]),
    enabled: Boolean(username),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  const dimensions = useMemo(() => {
    const payload = tasteQuery.data?.dimensions ?? {};
    return Object.entries(payload)
      .map(([dimension, traits]) => [dimension, (traits ?? []).slice(0, 6)] as const)
      .filter(([, traits]) => traits.length > 0);
  }, [tasteQuery.data]);

  if (tasteQuery.isError) return null;

  return (
    <motion.section
      className="analysis-panel"
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay }}
    >
      <div className="flex items-center gap-2">
        <Dna className="h-5 w-5 text-cinema-400" />
        <h2 className="text-xl font-semibold text-white">Taste profile</h2>
      </div>
      <p className="mt-1 text-sm text-white/60">
        What @{username} gravitates toward, from rated films with metadata.
      </p>

      {tasteQuery.isLoading && (
        <p className="mt-6 text-sm text-white/40">Reading taste signals…</p>
      )}

      {!tasteQuery.isLoading && dimensions.length === 0 && (
        <p className="mt-6 text-sm text-white/40">
          No metadata dimensions are ready for this profile yet.
        </p>
      )}

      <div className="mt-5 grid gap-5 md:grid-cols-2 xl:grid-cols-3">
        {dimensions.map(([dimension, traits]) => (
          <div key={dimension}>
            <p className="text-xs font-semibold uppercase tracking-wide text-white/45">
              {DIMENSION_LABELS[dimension] ?? dimension}
            </p>
            <ul className="mt-2 space-y-1.5">
              {traits.map((trait: TasteTrait) => {
                const score = Math.round(trait.group_score);
                return (
                  <li key={trait.id} className="flex items-center gap-2 text-sm">
                    <span
                      className="min-w-0 flex-1 truncate text-white/80"
                      title={trait.label}
                    >
                      {trait.label}
                    </span>
                    <span className="h-1.5 w-16 shrink-0 overflow-hidden rounded-full bg-white/10">
                      <span
                        className="block h-full rounded-full bg-cinema-500"
                        style={{ width: `${Math.max(2, score)}%` }}
                      />
                    </span>
                    {/* Without the sample size a trait built from two films
                        reads exactly like one built from twenty-five, and for a
                        single profile the score tops out at 100% on two
                        five-star films. */}
                    <span
                      className="w-9 shrink-0 text-right text-xs tabular-nums text-white/45"
                      title={`${score}% from ${trait.sample_size} ${trait.sample_size === 1 ? 'film' : 'films'}`}
                    >
                      {score}%
                    </span>
                    <span className="w-12 shrink-0 text-right text-[10px] tabular-nums text-white/30">
                      {trait.sample_size} {trait.sample_size === 1 ? 'film' : 'films'}
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>

      {dimensions.length > 0 && (
        <p className="mt-5 text-xs leading-5 text-white/35">
          Scores blend average rating with how much of this profile&apos;s history the
          trait covers. Traits backed by a single film rank last, since one rating
          says more about coverage than taste.
        </p>
      )}
    </motion.section>
  );
};

export default TasteProfilePanel;
