'use client';

import React from 'react';
import { motion } from 'framer-motion';
import { useQuery } from '@tanstack/react-query';
import { Telescope } from 'lucide-react';

import { obscurityApi } from '../../services/api';
import type { ObscurityCrowdPosition, ObscurityFilm, ObscurityLean } from '../../services/api';
import {
  FilmTitle,
  ListSection,
  MoviePoster,
  formatCompactCount,
  formatInsightCount,
  toMovieSummary,
} from './InsightUI';

/**
 * How the lean reads on screen. "Obscure" and "mainstream" are descriptions of
 * audience size, not of quality, so neither gets the good/bad colouring the
 * rating panels use for above/below.
 */
const LEAN_STYLES: Record<'obscure' | 'balanced' | 'mainstream', { panel: string; text: string }> = {
  obscure: { panel: 'border-cinema-400/25 bg-cinema-500/[0.08]', text: 'text-cinema-200' },
  balanced: { panel: 'border-white/10 bg-white/5', text: 'text-white/80' },
  mainstream: { panel: 'border-sky-400/25 bg-sky-500/[0.08]', text: 'text-sky-200' },
};

const LEAN_HEADLINES: Record<'obscure' | 'balanced' | 'mainstream', string> = {
  obscure: 'Watches smaller films than most of the circle',
  balanced: 'Watches films about as widely seen as the circle does',
  mainstream: 'Watches bigger films than most of the circle',
};

function leanStyle(lean: ObscurityLean | null) {
  return LEAN_STYLES[lean ?? 'balanced'];
}

function ratingsNote(count: number): string {
  return `${formatInsightCount(count)} ${count === 1 ? 'rating' : 'ratings'}`;
}

/** One film, sized by the crowd that rated it. */
function AudienceRow({ film }: { film: ObscurityFilm }) {
  return (
    <li className="flex items-center gap-3 rounded-xl border border-white/5 bg-black/20 px-3 py-2">
      <MoviePoster movie={toMovieSummary(film)} className="h-12 w-8" />
      <div className="min-w-0 flex-1">
        <FilmTitle film={film} />
        <p className="mt-0.5 text-[11px] leading-4 tabular-nums text-white/40">
          {`They rated it ${film.profile_rating.toFixed(1)}`}
        </p>
      </div>
      {film.rating_count !== null ? (
        <span
          className="shrink-0 rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-center text-white/70"
          title={`${ratingsNote(film.rating_count)} on Letterboxd`}
        >
          <span className="block text-xs font-semibold tabular-nums">
            {formatCompactCount(film.rating_count)}
          </span>
          <span className="block text-[9px] font-semibold uppercase tracking-wide text-white/35">
            ratings
          </span>
        </span>
      ) : null}
    </li>
  );
}

/**
 * Where one rating fell inside the crowd's own histogram. `share_at_or_below`
 * is stated as exactly what it is — the slice of the crowd sitting at or below
 * this rating — rather than translated into a verdict about the member.
 */
function CrowdPositionRow({ film }: { film: ObscurityCrowdPosition }) {
  const share = Math.max(0, Math.min(1, film.share_at_or_below));
  const percent = Math.round(share * 100);
  const references = [
    `They rated it ${film.profile_rating.toFixed(1)}`,
    film.crowd_average !== null ? `crowd average ${film.crowd_average.toFixed(2)}` : null,
  ].filter((note): note is string => note !== null);

  return (
    <li className="flex items-center gap-3 rounded-xl border border-white/5 bg-black/20 px-3 py-2">
      <MoviePoster movie={toMovieSummary(film)} className="h-12 w-8" />
      <div className="min-w-0 flex-1">
        <FilmTitle film={film} />
        <p className="mt-0.5 text-[11px] leading-4 tabular-nums text-white/40">
          {references.join(' · ')}
        </p>
      </div>
      <span
        className="shrink-0 rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-center text-white/70"
        title={`${percent}% of the crowd rated this film at or below ${film.profile_rating.toFixed(1)}`}
      >
        <span className="block text-xs font-semibold tabular-nums">{percent}%</span>
        <span className="block text-[9px] font-semibold uppercase tracking-wide text-white/35">
          at or below
        </span>
      </span>
    </li>
  );
}

/**
 * How mainstream a profile's taste is, measured in audience size.
 *
 * The headline is the median rather than the mean on purpose: audience sizes
 * run from a few hundred to several million, and one blockbuster would drag a
 * mean into a taste nobody has. The mean sits beside it so the skew stays
 * visible, and the lean is only ever relative to the other tracked profiles —
 * with nobody to compare against there is a median and no lean.
 *
 * The endpoint is optional from the page's point of view: any failure, and the
 * panel simply is not there.
 */
const ObscurityPanel: React.FC<{ username: string; delay?: number }> = ({
  username,
  delay = 0,
}) => {
  const obscurityQuery = useQuery({
    queryKey: ['obscurity', username],
    queryFn: () => obscurityApi.getObscurity(username),
    enabled: Boolean(username),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  const data = obscurityQuery.data;

  // No hooks below this line: the panel disappears entirely when the endpoint
  // is unavailable or has nothing to measure.
  if (obscurityQuery.isError || !data) return null;

  const coverage = data.coverage;
  const index = data.index;
  const mostObscure = data.most_obscure ?? [];
  const mostMainstream = data.most_mainstream ?? [];
  const crowdPosition = data.crowd_position ?? [];
  const crowdBelow = data.crowd_position_below ?? [];
  const crowdPercentile = data.crowd_percentile;
  const median = index?.median_rating_count ?? null;
  if (median === null && mostObscure.length === 0 && mostMainstream.length === 0) return null;

  const mean = index?.mean_rating_count ?? null;
  const percentile = index?.percentile_vs_group ?? null;
  const lean = index?.lean ?? null;
  const style = leanStyle(lean);

  const headline = median === null
    ? 'No audience size is known for these films yet'
    : `${formatInsightCount(median)} ratings behind the typical film they rated`;
  const headlineDetail = median === null
    ? 'Letterboxd’s crowd counts have not reached this profile’s films, so there is no median to report.'
    : mean !== null && mean > median
      ? `A median, not a mean: audience sizes are heavily right-skewed. The mean of ${formatInsightCount(mean)} sits above it, which is a handful of very large audiences showing up.`
      : 'A median rather than a mean, because audience sizes are heavily right-skewed.';

  const leanLabel = lean === null ? null : LEAN_HEADLINES[lean];

  // One qualification for the whole panel rather than a caveat on every row.
  const coverageNote = `The median reads ${formatInsightCount(coverage.films_with_rating_count)} of ${formatInsightCount(coverage.rated_films)} rated films — the rest have no Letterboxd audience size synced yet and are left out rather than counted as an audience of zero.`;
  const percentileNote = percentile === null
    ? 'There is no other tracked profile to place this median against, so no lean is claimed.'
    : null;

  return (
    <motion.section
      className="analysis-panel"
      aria-labelledby="obscurity-title"
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay }}
    >
      <div className="flex items-center gap-2">
        <Telescope className="h-5 w-5 text-cinema-400" aria-hidden="true" />
        <h2 id="obscurity-title" className="text-xl font-semibold text-white">
          Obscurity index
        </h2>
      </div>
      <p className="mt-1 text-sm text-white/60">
        How big a crowd @{username} tends to watch with — Letterboxd publishes a film’s
        rating count and never adds it up across a member’s history.
      </p>

      <div
        className={`mt-5 flex flex-col gap-4 rounded-2xl border px-4 py-4 sm:flex-row sm:items-center sm:justify-between ${style.panel}`}
      >
        <div className="flex min-w-0 items-start gap-3">
          <Telescope className={`mt-0.5 h-6 w-6 shrink-0 ${style.text}`} aria-hidden="true" />
          <div className="min-w-0">
            <p className={`text-lg font-semibold ${style.text}`}>{headline}</p>
            {leanLabel ? (
              <p className="mt-0.5 text-sm font-medium text-white/70">{leanLabel}</p>
            ) : null}
            <p className="mt-1 text-xs leading-5 text-white/45">{headlineDetail}</p>
          </div>
        </div>
        {percentile !== null ? (
          <div className="shrink-0 sm:text-right">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-white/45">
              Obscurity percentile
            </p>
            <p className="mt-0.5 text-lg font-bold tabular-nums text-white">
              {percentile.toFixed(0)}
            </p>
            <p className="text-[11px] text-white/40">
              100 = every other tracked profile watches bigger films
            </p>
          </div>
        ) : null}
      </div>

      {mostObscure.length > 0 || mostMainstream.length > 0 ? (
        <div className="mt-6 grid gap-6 lg:grid-cols-2">
          {mostObscure.length > 0 ? (
            <ListSection title="Most obscure" subtitle="Smallest audiences they have rated">
              {mostObscure.map((film, index_) => (
                <AudienceRow key={`${film.title}-${film.year ?? 'na'}-${index_}`} film={film} />
              ))}
            </ListSection>
          ) : null}
          {mostMainstream.length > 0 ? (
            <ListSection title="Most mainstream" subtitle="Biggest audiences they have rated">
              {mostMainstream.map((film, index_) => (
                <AudienceRow key={`${film.title}-${film.year ?? 'na'}-${index_}`} film={film} />
              ))}
            </ListSection>
          ) : null}
        </div>
      ) : null}

      {crowdPosition.length > 0 ? (
        <div className="mt-6 space-y-4">
          {crowdPercentile && crowdPercentile.typical_share !== null ? (
            /* The tails below are the extremes; this is where they usually sit.
               Showing only the extremes told half the story. */
            <p className="rounded-lg border border-white/[0.07] bg-black/15 px-3 py-2 text-xs leading-5 text-white/50">
              Across {crowdPercentile.measured_films.toLocaleString()} rated films with a
              crowd histogram, they typically rate above{' '}
              <strong className="text-white/80">
                {Math.round(crowdPercentile.typical_share * 100)}%
              </strong>{' '}
              of the people who rated the same film
              {crowdPercentile.lean && crowdPercentile.lean !== 'typical'
                ? ` — a ${crowdPercentile.lean} hand overall`
                : ' — right about average'}
              .
            </p>
          ) : null}
          <ListSection
            title="Furthest above the crowd"
            subtitle="Where their rating fell inside Letterboxd’s own histogram for the film"
          >
            {crowdPosition.map((film, index_) => (
              <CrowdPositionRow key={`${film.title}-${film.year ?? 'na'}-${index_}`} film={film} />
            ))}
          </ListSection>
          {crowdBelow.length > 0 ? (
            <ListSection
              title="Furthest below the crowd"
              subtitle="Films they rated lower than almost everyone who rated them"
            >
              {crowdBelow.map((film, index_) => (
                <CrowdPositionRow key={`below-${film.title}-${film.year ?? 'na'}-${index_}`} film={film} />
              ))}
            </ListSection>
          ) : null}
        </div>
      ) : null}

      <p className="mt-5 text-[11px] leading-5 text-white/30">
        {[coverageNote, percentileNote]
          .filter((note): note is string => note !== null)
          .join(' ')}
      </p>
    </motion.section>
  );
};

export default ObscurityPanel;
