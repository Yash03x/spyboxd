'use client';

import React from 'react';
import Link from 'next/link';
import { AlertTriangle, CheckCircle2, CircleSlash, Film, Info, Loader2, UserCheck } from 'lucide-react';

import type { FeatureCoverage, MovieSummary, ProfileInfo } from '../../services/api';

/** A film as the flat panel endpoints ship it, before it reaches a poster. */
type FilmShell = {
  title: string;
  year: number | null;
  poster_url: string | null;
  letterboxd_url: string | null;
};

export function formatInsightCount(value: number): string {
  return value.toLocaleString();
}

/**
 * Big audience numbers, shortened. A film with six million ratings and one
 * with two hundred sit in the same column, and the exact figure is kept in the
 * caller's `title` where it still matters.
 */
export function formatCompactCount(value: number): string {
  return new Intl.NumberFormat(undefined, {
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(value);
}

export function filmLabel(film: { title: string; year: number | null }): string {
  return film.year ? `${film.title} (${film.year})` : film.title;
}

/**
 * The panel endpoints return flat film shells rather than the full
 * `MovieSummary` the shared poster expects; only the artwork is read from it.
 */
export function toMovieSummary(film: FilmShell): MovieSummary {
  return {
    movie_id: null,
    tmdb_id: null,
    letterboxd_slug: null,
    letterboxd_url: film.letterboxd_url,
    title: film.title,
    year: film.year,
    poster_url: film.poster_url,
  };
}

export function FilmTitle({ film }: {
  film: { title: string; year: number | null; letterboxd_url: string | null };
}) {
  const label = filmLabel(film);
  return (
    <p className="truncate text-sm font-medium text-white/85" title={label}>
      {film.letterboxd_url ? (
        <a
          href={film.letterboxd_url}
          target="_blank"
          rel="noopener noreferrer"
          className="hover:text-cinema-200 hover:underline"
        >
          {label}
        </a>
      ) : (
        label
      )}
    </p>
  );
}

/** A titled list inside a panel, so every panel's lists read the same way. */
export function ListSection({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string | null;
  children: React.ReactNode;
}) {
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-wide text-white/45">{title}</p>
      {subtitle ? <p className="mt-0.5 text-[11px] text-white/30">{subtitle}</p> : null}
      <ul className="mt-2 space-y-1.5">{children}</ul>
    </div>
  );
}

/**
 * The marker for a gap co-watch where the later watcher already followed the
 * earlier one.
 *
 * The wording is the ceiling the data supports and must not be raised: a follow
 * edge is an observed social link, never evidence that one member's watch
 * caused another's. Nothing here says "influenced", "picked up from", or
 * "because of".
 */
export function FollowsEarlierWatcherMarker({
  earlierWatcher,
  laterWatcher,
}: {
  earlierWatcher?: string | null;
  laterWatcher?: string | null;
}) {
  const who = earlierWatcher && laterWatcher
    ? `@${laterWatcher} watched after @${earlierWatcher}, whom they already follow. `
    : '';
  return (
    <span
      title={`${who}A follow is an observed social link, not evidence that one member's watch caused another's.`}
      className="inline-flex items-center gap-1.5 rounded-full border border-cinema-400/30 bg-cinema-500/10 px-2.5 py-1 text-[11px] font-semibold text-cinema-200"
    >
      <UserCheck className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      Watched after someone they follow
    </span>
  );
}

export function formatCalendarDate(value: string | null | undefined): string {
  if (!value) return 'Date unavailable';
  const [year, month, day] = value.split('-').map(Number);
  if (!year || !month || !day) return value;
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  }).format(new Date(year, month - 1, day));
}

const AVATAR_DIMENSIONS = {
  sm: 'h-7 w-7 text-[10px]',
  md: 'h-9 w-9 text-xs',
  lg: 'h-11 w-11 text-sm',
  // Hero treatment for a full profile header.
  xl: 'h-20 w-20 text-xl sm:h-24 sm:w-24 sm:text-2xl',
} as const;

export function ProfileAvatar({ profile, username, size = 'md' }: {
  profile?: Pick<ProfileInfo, 'username'> & Partial<Pick<ProfileInfo, 'profile_image_url' | 'avatar_url'>>;
  username?: string;
  size?: keyof typeof AVATAR_DIMENSIONS;
}) {
  const name = profile?.username ?? username ?? '?';
  const imageUrl = profile?.profile_image_url ?? profile?.avatar_url;
  const [failedUrl, setFailedUrl] = React.useState<string | null>(null);
  const dimensions = AVATAR_DIMENSIONS[size];

  if (imageUrl && imageUrl !== failedUrl) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={imageUrl}
        alt=""
        onError={() => setFailedUrl(imageUrl)}
        className={`${dimensions} shrink-0 rounded-full border border-cinema-400/35 object-cover`}
      />
    );
  }

  return (
    <span
      aria-hidden="true"
      className={`${dimensions} flex shrink-0 items-center justify-center rounded-full border border-cinema-400/35 bg-cinema-500/15 font-bold uppercase text-cinema-200`}
    >
      {name.slice(0, 2)}
    </span>
  );
}

export function MoviePoster({ movie, className = '' }: { movie: MovieSummary; className?: string }) {
  const [failedUrl, setFailedUrl] = React.useState<string | null>(null);
  const posterUrl = movie.poster_url?.trim() || null;

  if (posterUrl && posterUrl !== failedUrl) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={posterUrl}
        alt=""
        onError={() => setFailedUrl(posterUrl)}
        className={`shrink-0 rounded-md border border-white/10 object-cover ${className}`}
      />
    );
  }

  return (
    <span className={`flex shrink-0 items-center justify-center rounded-md border border-white/10 bg-white/5 text-white/35 ${className}`}>
      <Film className="h-5 w-5" aria-hidden="true" />
    </span>
  );
}

export function WorkspaceTabs<T extends string>({
  activeTab,
  items,
  onChange,
}: {
  activeTab: T;
  items: Array<{ id: T; label: string }>;
  onChange: (tab: T) => void;
}) {
  return (
    <div className="flex min-w-0 gap-1 overflow-x-auto border-b border-white/10" role="tablist" aria-label="Compare views">
      {items.map((item) => {
        const selected = item.id === activeTab;
        return (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={selected}
            onClick={() => onChange(item.id)}
            className={`relative min-w-max px-5 py-3 text-sm font-semibold transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-cinema-400/70 ${
              selected ? 'text-white' : 'text-white/55 hover:text-white/85'
            }`}
          >
            {item.label}
            {selected && <span className="absolute inset-x-0 bottom-0 h-0.5 bg-cinema-500" />}
          </button>
        );
      })}
    </div>
  );
}

export function CoverageBadge({ coverage }: { coverage: FeatureCoverage }) {
  const config = coverage.status === 'ready'
    ? { icon: CheckCircle2, label: 'Ready', classes: 'border-emerald-400/25 bg-emerald-500/10 text-emerald-300' }
    : coverage.status === 'partial'
      ? { icon: AlertTriangle, label: 'Partial data', classes: 'border-amber-400/25 bg-amber-500/10 text-amber-300' }
      : { icon: CircleSlash, label: 'Blocked', classes: 'border-red-400/25 bg-red-500/10 text-red-300' };
  const Icon = config.icon;
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold ${config.classes}`}>
      <Icon className="h-3.5 w-3.5" />
      {config.label}
    </span>
  );
}

export function CoverageBanner({ coverage, onViewCoverage }: {
  coverage: FeatureCoverage;
  onViewCoverage?: () => void;
}) {
  const message = coverage.status === 'ready'
    ? 'The selected profiles have enough imported data for this view.'
    : coverage.status === 'partial'
      ? coverage.warnings[0] ?? 'Results use the available watch history and may be incomplete.'
      : coverage.blockers[0] ?? 'More profile data is required before this view can be calculated.';

  return (
    <aside className={`flex flex-col gap-3 rounded-xl border px-4 py-3 sm:flex-row sm:items-center sm:justify-between ${
      coverage.status === 'blocked'
        ? 'border-red-400/25 bg-red-500/[0.06]'
        : coverage.status === 'partial'
          ? 'border-cinema-400/25 bg-cinema-500/[0.06]'
          : 'border-emerald-400/20 bg-emerald-500/[0.04]'
    }`}>
      <div className="flex min-w-0 items-start gap-3">
        <Info className="mt-0.5 h-5 w-5 shrink-0 text-cinema-400" />
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-semibold text-white">Data coverage</p>
            <CoverageBadge coverage={coverage} />
          </div>
          <p className="mt-1 text-xs leading-5 text-white/55">
            {message} {coverage.total_watch_events > 0 ? `${coverage.dated_watch_events.toLocaleString()} of ${coverage.total_watch_events.toLocaleString()} watch events are dated.` : ''}
          </p>
        </div>
      </div>
      {onViewCoverage && (
        <button type="button" onClick={onViewCoverage} className="btn-ghost shrink-0 border-white/10 px-3 py-2 text-xs">
          View coverage
        </button>
      )}
    </aside>
  );
}

export function ScoreRing({ score, label = 'Group fit', size = 'md' }: {
  score: number;
  label?: string;
  size?: 'sm' | 'md' | 'lg';
}) {
  const boundedScore = Math.max(0, Math.min(100, Math.round(score)));
  const dimensions = size === 'lg' ? 'h-20 w-20' : size === 'sm' ? 'h-12 w-12' : 'h-14 w-14';
  return (
    <div className="text-center">
      <div
        className={`${dimensions} mx-auto grid place-items-center rounded-full p-[3px]`}
        style={{ background: `conic-gradient(#f57c00 ${boundedScore * 3.6}deg, rgba(255,255,255,.1) 0deg)` }}
      >
        <div className="grid h-full w-full place-items-center rounded-full bg-noir-900 text-base font-bold text-white">
          {boundedScore}
        </div>
      </div>
      <p className="mt-1 text-[10px] text-white/45">{label}</p>
    </div>
  );
}

export function FeatureState({
  title,
  message,
  loading = false,
  actionHref,
  actionLabel,
}: {
  title: string;
  message: string;
  loading?: boolean;
  actionHref?: string;
  actionLabel?: string;
}) {
  return (
    <section className="card-cinema flex min-h-72 flex-col items-center justify-center text-center">
      <span className="grid h-12 w-12 place-items-center rounded-xl border border-cinema-400/25 bg-cinema-500/10 text-cinema-300">
        {loading ? <Loader2 className="h-6 w-6 animate-spin" /> : <CircleSlash className="h-6 w-6" />}
      </span>
      <h2 className="mt-4 text-lg font-semibold text-white">{title}</h2>
      <p className="mt-2 max-w-lg text-sm leading-6 text-white/50">{message}</p>
      {actionHref && actionLabel && (
        <Link href={actionHref} className="btn-primary mt-5 px-5 py-2 text-sm">
          {actionLabel}
        </Link>
      )}
    </section>
  );
}
