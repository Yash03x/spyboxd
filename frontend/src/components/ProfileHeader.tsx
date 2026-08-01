'use client';

import React from 'react';
import { motion } from 'framer-motion';
import { BadgeCheck, Globe, Heart, MapPin, RefreshCw, Users } from 'lucide-react';

import { MoviePoster, ProfileAvatar } from './insights/InsightUI';
import type { MovieSummary, ProfileFavoriteFilm, ProfileHeader as ProfileHeaderData } from '../services/api';

type StatItem = {
  label: string;
  value: number;
  hint?: string;
};

type ExtraItem = {
  label: string;
  value: string;
  hint?: string;
};

function formatCount(value: number): string {
  return value.toLocaleString();
}

function formatMonthYear(value: string | null): string | null {
  if (!value) return null;
  const [year, month] = value.split('-').map(Number);
  if (!year || !month) return null;
  return new Intl.DateTimeFormat(undefined, { month: 'long', year: 'numeric' }).format(
    new Date(year, month - 1, 1),
  );
}

function formatTimestamp(value: string | null): string | null {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed.toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  });
}

/**
 * Letterboxd's stats page labels vary by account tier, so keys arrive as
 * whatever the page published ("hours", "longest_streak", "2_film_days").
 * Render them generically instead of guessing a fixed set.
 */
function humanizeStatKey(key: string): string {
  const words = key.replace(/[_-]+/g, ' ').trim();
  if (!words) return key;
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function formatStatValue(value: number | string): string {
  return typeof value === 'number' ? formatCount(value) : value;
}

function favoriteToMovieSummary(favorite: ProfileFavoriteFilm): MovieSummary {
  return {
    movie_id: null,
    tmdb_id: null,
    letterboxd_slug: null,
    letterboxd_url: favorite.letterboxd_url,
    title: favorite.title,
    year: favorite.year,
    poster_url: favorite.poster_url,
  };
}

function FavoritePoster({ favorite }: { favorite: ProfileFavoriteFilm }) {
  const label = favorite.year ? `${favorite.title} (${favorite.year})` : favorite.title;
  const poster = (
    <>
      <MoviePoster movie={favoriteToMovieSummary(favorite)} className="aspect-[2/3] w-full" />
      <p className="mt-2 line-clamp-2 text-xs font-medium text-white/70 group-hover:text-white">
        {label}
      </p>
    </>
  );

  if (favorite.letterboxd_url) {
    return (
      <a
        href={favorite.letterboxd_url}
        target="_blank"
        rel="noreferrer"
        className="group block rounded-xl focus:outline-none focus-visible:ring-2 focus-visible:ring-cinema-400/70"
        title={`${label} on Letterboxd`}
      >
        {poster}
      </a>
    );
  }

  return <div className="group block">{poster}</div>;
}

export default function ProfileHeader({
  header,
  tagCount,
  delay = 0,
}: {
  header?: ProfileHeaderData | null;
  tagCount?: number;
  delay?: number;
}) {
  if (!header) {
    return null;
  }

  const displayName = header.display_name?.trim() || header.username;
  const bio = header.bio?.trim();
  const location = header.location?.trim();
  const pronoun = header.pronoun?.trim();
  const badge = header.member_badge?.trim();
  const joinedLabel = formatMonthYear(header.join_date);

  // A member can list several links (personal site, Twitter, …). Older
  // payloads only carry the single website field, so fall back to it. Plain
  // computation rather than useMemo: this component returns early when it has
  // no header, so a hook here would not run in the same order every render.
  const observedLinks = header.external_links?.filter((link) => link.url) ?? [];
  const externalLinks = observedLinks.length > 0
    ? observedLinks
    : header.website_url
      ? [{ label: header.website ?? header.website_url, url: header.website_url }]
      : [];

  // Letterboxd's own header stat row. Anything it never observed is dropped
  // rather than rendered as a blank or a misleading zero.
  const statCandidates: Array<StatItem | null> = [
    header.films_count !== null
      ? { label: 'Films', value: header.films_count }
      : header.synced_films !== null
        ? { label: 'Films', value: header.synced_films, hint: 'synced' }
        : null,
    header.films_this_year !== null
      ? { label: 'This year', value: header.films_this_year, hint: 'from synced diary' }
      : null,
    header.reviews_count !== null ? { label: 'Reviews', value: header.reviews_count } : null,
    header.lists_count !== null ? { label: 'Lists', value: header.lists_count } : null,
    header.following_count !== null ? { label: 'Following', value: header.following_count } : null,
    header.followers_count !== null ? { label: 'Followers', value: header.followers_count } : null,
    header.watchlist_count !== null ? { label: 'Watchlist', value: header.watchlist_count } : null,
  ];
  const stats = statCandidates.filter((item): item is StatItem => item !== null);

  const favorites = header.favorites ?? [];

  const syncedAt = formatTimestamp(header.last_scraped_at);
  const metadataSyncedAt = formatTimestamp(header.metadata_synced_at);
  const statsSyncedAt = formatTimestamp(header.stats_synced_at);

  const extraCandidates: Array<ExtraItem | null> = [
    syncedAt ? { label: 'Last synced', value: syncedAt } : null,
    metadataSyncedAt && metadataSyncedAt !== syncedAt
      ? { label: 'Profile details synced', value: metadataSyncedAt }
      : null,
    header.avg_rating !== null
      ? { label: 'Average rating', value: `${header.avg_rating.toFixed(2)} stars` }
      : null,
    // Only worth a tile when our synced dataset disagrees with Letterboxd's
    // own counter; an identical number is noise beside the stat row above.
    header.synced_films !== null && header.synced_films !== header.films_count
      ? { label: 'Films in Spyboxd', value: formatCount(header.synced_films) }
      : null,
    header.total_reviews !== null && header.total_reviews !== header.reviews_count
      ? { label: 'Reviews stored', value: formatCount(header.total_reviews) }
      : null,
    tagCount !== undefined && tagCount > 0
      ? { label: 'Distinct tags used', value: formatCount(tagCount) }
      : null,
  ];
  const extras = extraCandidates.filter((item): item is ExtraItem => item !== null);

  const letterboxdStats = Object.entries(header.stats_snapshot ?? {}).filter(
    ([, value]) => value !== null && value !== undefined && value !== '',
  );

  return (
    <motion.section
      className="analysis-panel"
      aria-labelledby="profile-header-name"
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay }}
    >
      <div className="flex flex-col gap-5 sm:flex-row sm:items-start">
        <ProfileAvatar
          profile={{ username: header.username, avatar_url: header.avatar_url }}
          size="xl"
        />

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <h2 id="profile-header-name" className="text-2xl font-bold text-white sm:text-3xl">
              {displayName}
            </h2>
            {badge ? (
              <span className="inline-flex items-center gap-1 rounded-full border border-cinema-400/30 bg-cinema-500/15 px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide text-cinema-200">
                <BadgeCheck className="h-3.5 w-3.5" aria-hidden="true" />
                {badge}
              </span>
            ) : null}
          </div>

          <a
            href={header.letterboxd_url}
            target="_blank"
            rel="noreferrer"
            className="mt-1 inline-block text-sm font-medium text-white/55 transition-colors hover:text-cinema-300"
          >
            @{header.username}
          </a>

          {bio ? (
            <p className="mt-3 max-w-2xl whitespace-pre-line text-sm leading-6 text-white/75">{bio}</p>
          ) : null}

          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-white/55">
            {location ? (
              <span className="inline-flex items-center gap-1.5">
                <MapPin className="h-3.5 w-3.5 text-cinema-400" aria-hidden="true" />
                {location}
              </span>
            ) : null}
            {pronoun ? (
              <span className="inline-flex items-center gap-1.5">
                <Users className="h-3.5 w-3.5 text-cinema-400" aria-hidden="true" />
                {pronoun}
              </span>
            ) : null}
            {externalLinks.map((link) => (
              <a
                key={link.url}
                href={link.url}
                target="_blank"
                rel="noreferrer nofollow"
                className="inline-flex max-w-full items-center gap-1.5 truncate text-white/70 transition-colors hover:text-cinema-300"
              >
                <Globe className="h-3.5 w-3.5 text-cinema-400" aria-hidden="true" />
                <span className="truncate">{link.label}</span>
              </a>
            ))}
            {joinedLabel ? <span>Joined {joinedLabel}</span> : null}
          </div>
        </div>
      </div>

      {stats.length > 0 ? (
        <dl className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-7">
          {stats.map((stat) => (
            <div
              key={stat.label}
              className="rounded-xl border border-white/10 bg-white/5 px-3 py-2.5 text-center"
            >
              <dt className="text-[10px] font-semibold uppercase tracking-wide text-white/45">
                {stat.label}
              </dt>
              <dd className="mt-1 text-lg font-bold text-white">{formatCount(stat.value)}</dd>
              {stat.hint ? (
                <p className="mt-0.5 text-[10px] text-white/35">{stat.hint}</p>
              ) : null}
            </div>
          ))}
        </dl>
      ) : null}

      {favorites.length > 0 ? (
        <div className="mt-6">
          <h3 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-white/60">
            <Heart className="h-4 w-4 text-cinema-400" aria-hidden="true" />
            Favourite films
          </h3>
          <div className="mt-3 grid max-w-2xl grid-cols-2 gap-3 sm:grid-cols-4">
            {favorites.map((favorite) => (
              <FavoritePoster
                key={`${favorite.position}-${favorite.title}-${favorite.year ?? 'na'}`}
                favorite={favorite}
              />
            ))}
          </div>
        </div>
      ) : null}

      {extras.length > 0 || letterboxdStats.length > 0 ? (
        <div className="mt-6 rounded-2xl border border-cinema-400/20 bg-cinema-500/5 p-4">
          <h3 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-cinema-200">
            <RefreshCw className="h-4 w-4" aria-hidden="true" />
            Spyboxd extras
          </h3>
          <p className="mt-1 text-xs text-white/50">
            Context Letterboxd&rsquo;s profile page does not show.
          </p>

          {extras.length > 0 ? (
            <dl className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {extras.map((extra) => (
                <div key={extra.label} className="rounded-xl border border-white/10 bg-white/5 px-3 py-2.5">
                  <dt className="text-[10px] font-semibold uppercase tracking-wide text-white/45">
                    {extra.label}
                  </dt>
                  <dd className="mt-1 text-sm font-semibold text-white">{extra.value}</dd>
                </div>
              ))}
            </dl>
          ) : null}

          {letterboxdStats.length > 0 ? (
            <div className="mt-4 border-t border-white/10 pt-4">
              <p className="text-xs text-white/55">
                Letterboxd&rsquo;s own stats page figures
                {statsSyncedAt ? `, read ${statsSyncedAt}` : ''}
              </p>
              <dl className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
                {letterboxdStats.map(([key, value]) => (
                  <div key={key} className="rounded-xl border border-white/10 bg-white/5 px-3 py-2.5">
                    <dt className="text-[10px] font-semibold uppercase tracking-wide text-white/45">
                      {humanizeStatKey(key)}
                    </dt>
                    <dd className="mt-1 text-sm font-semibold text-white">{formatStatValue(value)}</dd>
                  </div>
                ))}
              </dl>
            </div>
          ) : null}
        </div>
      ) : null}
    </motion.section>
  );
}
