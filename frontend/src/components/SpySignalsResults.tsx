'use client';

import React, { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import {
  CalendarDays,
  Clock3,
  Film,
  Link2,
  Radar,
  Star,
  Users,
  Zap,
} from 'lucide-react';

import type {
  GroupSignalEvent,
  GroupSignalMovie,
  GroupSignalPair,
  GroupSignals,
} from '../services/api';
import type { SignalGapDays } from './SpySignalsControls';

interface SpySignalsResultsProps {
  groupSignals: GroupSignals;
  gapDays: SignalGapDays;
  selectedProfileCount: number;
}

const dateFormatter = new Intl.DateTimeFormat(undefined, {
  month: 'short',
  day: 'numeric',
  year: 'numeric',
});

function parseIsoDate(value: string): Date {
  const [year, month, day] = value.split('-').map(Number);
  return new Date(year, month - 1, day);
}

function formatDate(value: string): string {
  return dateFormatter.format(parseIsoDate(value));
}

function formatNumber(value: number | null | undefined, digits = 1): string {
  return value === null || value === undefined ? 'n/a' : value.toFixed(digits);
}

function formatMovie(title: string, year: number | null): string {
  return year ? `${title} (${year})` : title;
}

function getWindowDays(event: GroupSignalEvent): number {
  if (event.day_gap !== undefined) return event.day_gap;
  const startParts = event.start_date.split('-').map(Number) as [number, number, number];
  const endParts = event.end_date.split('-').map(Number) as [number, number, number];
  const start = Date.UTC(startParts[0], startParts[1] - 1, startParts[2]);
  const end = Date.UTC(endParts[0], endParts[1] - 1, endParts[2]);
  return Math.max(0, Math.round((end - start) / 86_400_000));
}

function eventKey(event: GroupSignalEvent): string {
  return `${event.title}-${event.year ?? 'na'}-${event.start_date}-${event.end_date}`;
}

function eventsForGap(groupSignals: GroupSignals, gapDays: SignalGapDays): GroupSignalEvent[] {
  let events: GroupSignalEvent[];
  if (groupSignals.gap_events) {
    events = groupSignals.gap_events;
  } else if (gapDays === 0) {
    events = groupSignals.same_day_events;
  } else {
    events = [...groupSignals.same_day_events, ...groupSignals.one_day_gap_events];
  }

  return Array.from(new Map(events.map((event) => [eventKey(event), event])).values()).sort(
    (left, right) => right.end_date.localeCompare(left.end_date) || right.start_date.localeCompare(left.start_date),
  );
}

function gapLabel(gapDays: SignalGapDays): string {
  if (gapDays === 0) return 'same-day';
  if (gapDays === 1) return '1-day';
  return `${gapDays}-day`;
}

function Initials({ username }: { username: string }) {
  return (
    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-cinema-400/30 bg-cinema-500/15 text-[11px] font-bold uppercase text-cinema-200">
      {username.slice(0, 2)}
    </span>
  );
}

const MetricCard: React.FC<{
  icon: React.ComponentType<{ className?: string }>;
  value: React.ReactNode;
  title: string;
  subtitle: string;
  delay: number;
  valueClassName?: string;
}> = ({ icon: Icon, value, title, subtitle, delay, valueClassName = 'break-words text-2xl' }) => (
  <motion.div
    className="card-cinema flex min-h-36 items-start gap-4 p-5"
    initial={{ opacity: 0, y: 16 }}
    animate={{ opacity: 1, y: 0 }}
    transition={{ delay, duration: 0.4 }}
  >
    <span className="mt-1 rounded-xl border border-cinema-400/25 bg-cinema-500/10 p-2.5 text-cinema-400">
      <Icon className="h-6 w-6" />
    </span>
    <div className="min-w-0">
      <p className={`${valueClassName} font-bold leading-tight text-white text-glow`}>{value}</p>
      <p className="mt-1 text-sm font-semibold text-white/90">{title}</p>
      <p className="mt-2 text-xs leading-5 text-white/50">{subtitle}</p>
    </div>
  </motion.div>
);

function SignalStrength({ event }: { event: GroupSignalEvent }) {
  const gap = event.max_rating_gap;
  const strength = gap === null || gap === undefined
    ? { label: 'Ratings unavailable', classes: 'border-white/15 bg-white/5 text-white/50' }
    : gap <= 0.5
      ? { label: 'Strong', classes: 'border-emerald-400/40 bg-emerald-500/10 text-emerald-300' }
      : gap <= 1.5
        ? { label: 'Moderate', classes: 'border-amber-400/40 bg-amber-500/10 text-amber-300' }
        : { label: 'Divisive', classes: 'border-red-400/40 bg-red-500/10 text-red-300' };

  return (
    <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${strength.classes}`}>
      {strength.label}
    </span>
  );
}

const SignalEventCard: React.FC<{ event: GroupSignalEvent; index: number }> = ({ event, index }) => {
  const windowDays = getWindowDays(event);
  return (
    <motion.article
      className="relative overflow-hidden rounded-xl border border-white/10 bg-white/[0.035] transition-colors hover:border-cinema-400/25 hover:bg-white/[0.055]"
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: Math.min(index * 0.035, 0.3) }}
    >
      <div className="flex flex-col sm:flex-row">
        <div className="relative flex shrink-0 items-center gap-3 border-b border-white/10 px-4 py-3 sm:w-40 sm:flex-col sm:items-start sm:justify-center sm:border-b-0 sm:border-r">
          <span className="absolute bottom-0 left-0 top-0 w-0.5 bg-cinema-500 sm:-right-px sm:left-auto" />
          <div>
            <p className="text-xs leading-5 text-white/50">
              {event.start_date === event.end_date
                ? formatDate(event.start_date)
                : <>{formatDate(event.start_date)}<br aria-hidden="true" />→ {formatDate(event.end_date)}</>}
            </p>
            <p className="mt-0.5 text-sm font-semibold text-cinema-300">
              {windowDays === 0 ? 'Same day' : `${windowDays} day${windowDays === 1 ? '' : 's'} apart`}
            </p>
          </div>
          <span className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-[11px] text-white/55">
            {windowDays === 0 ? 'Co-watch' : 'Watch echo'}
          </span>
        </div>

        <div className="flex min-w-0 flex-1 gap-4 p-4">
          <div className="hidden h-20 w-14 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-gradient-to-br from-white/10 to-black/20 text-cinema-400 sm:flex">
            <Film className="h-6 w-6" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h3 className="text-lg font-semibold text-white">
                  {event.title}
                  {event.year && <span className="ml-2 text-sm font-normal text-white/45">({event.year})</span>}
                </h3>
                <p className="mt-1 text-xs text-white/45">
                  {event.profile_count} profiles · {event.pair_count} pair {event.pair_count === 1 ? 'match' : 'matches'}
                </p>
              </div>
              <SignalStrength event={event} />
            </div>

            <div className="mt-3 flex flex-wrap gap-2">
              {event.participants.map((participant) => (
                <div
                  key={`${participant.username}-${participant.watched_date ?? 'na'}`}
                  className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 py-1.5 pl-1.5 pr-3"
                >
                  <Initials username={participant.username} />
                  <div>
                    <p className="max-w-32 truncate text-xs font-medium text-white/80">{participant.username}</p>
                    <p className="mt-0.5 flex flex-wrap items-center gap-x-1 text-[11px] text-white/45">
                      <span>{participant.watched_date ? formatDate(participant.watched_date) : 'Date unavailable'}</span>
                      <span aria-hidden="true">·</span>
                      {participant.rating !== null ? (
                        <span className="flex items-center gap-1"><Star className="h-3 w-3 fill-cinema-400 text-cinema-400" /> {participant.rating.toFixed(1)}</span>
                      ) : <span>Unrated</span>}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="hidden w-24 shrink-0 self-center text-right lg:block">
            <p className="text-xs text-white/45">{event.participants.filter((participant) => participant.rating !== null).length}-of-{event.profile_count} rated</p>
            <p className="mt-1 text-sm font-medium text-white/70">
              Avg {formatNumber(event.average_rating)}
            </p>
          </div>
        </div>
      </div>
    </motion.article>
  );
};

function StrongestPairCard({ pair, gapDays }: { pair: GroupSignalPair | null; gapDays: SignalGapDays }) {
  if (!pair) {
    return (
      <ContextCard title="Strongest Pair" icon={Link2}>
        <p className="text-sm text-white/50">No pair has enough overlapping activity to score yet.</p>
      </ContextCard>
    );
  }

  const coWatches = gapDays === 0
    ? pair.same_day_count
    : gapDays === 1
      ? pair.same_day_count + pair.one_day_gap_count
      : pair.within_gap_count ?? pair.tight_window_count;

  return (
    <ContextCard title="Strongest Pair" icon={Link2}>
      <div className="flex items-center justify-center gap-3">
        <ProfileIdentity username={pair.profiles[0] ?? 'Unknown'} />
        <Link2 className="h-4 w-4 shrink-0 text-cinema-400" />
        <ProfileIdentity username={pair.profiles[1] ?? 'Unknown'} align="right" />
      </div>
      <div className="mt-5 text-center">
        <p className="text-2xl font-bold text-white">{coWatches}</p>
        <p className="mt-1 text-xs text-white/50">{gapLabel(gapDays)} co-watches</p>
      </div>
      <div className="mt-4 grid grid-cols-2 divide-x divide-white/10 border-t border-white/10 pt-4 text-center">
        <div>
          <p className="text-sm font-semibold text-white/85">{formatNumber(pair.alignment_score)}</p>
          <p className="text-[11px] text-white/45">Alignment</p>
        </div>
        <div>
          <p className="text-sm font-semibold text-white/85">{formatNumber(pair.average_rating_gap)}</p>
          <p className="text-[11px] text-white/45">Avg rating gap</p>
        </div>
      </div>
    </ContextCard>
  );
}

function MostDivisiveCard({ movie }: { movie: GroupSignalMovie | null }) {
  if (!movie) {
    return (
      <ContextCard title="Most Divisive" icon={Zap}>
        <p className="text-sm text-white/50">No shared ratings are available to measure disagreement.</p>
      </ContextCard>
    );
  }

  return (
    <ContextCard title="Most Divisive" icon={Zap}>
      <p className="text-center text-sm font-semibold text-white">{formatMovie(movie.title, movie.year)}</p>
      <p className="mt-3 text-center text-xs leading-5 text-white/45">
        {movie.profile_count} profiles contributed {movie.rating_count} ratings. The data does not identify which two produced the maximum gap.
      </p>
      <div className="mt-5 text-center">
        <p className="text-2xl font-bold text-red-400">{formatNumber(movie.max_rating_gap)} ★</p>
        <p className="mt-1 text-xs text-white/50">Maximum rating gap</p>
      </div>
      <div className="mt-4 grid grid-cols-2 divide-x divide-white/10 border-t border-white/10 pt-4 text-center">
        <div>
          <p className="text-sm font-semibold text-white/85">{movie.rating_count}</p>
          <p className="text-[11px] text-white/45">Ratings</p>
        </div>
        <div>
          <p className="text-sm font-semibold text-white/85">{formatNumber(movie.average_rating)}</p>
          <p className="text-[11px] text-white/45">Average</p>
        </div>
      </div>
    </ContextCard>
  );
}

const ProfileIdentity: React.FC<{ username: string; align?: 'left' | 'right' }> = ({
  username,
  align = 'left',
}) => (
  <div className={`flex min-w-0 items-center gap-2 ${align === 'right' ? 'flex-row-reverse text-right' : ''}`}>
    <Initials username={username} />
    <span className="max-w-24 truncate text-xs font-medium text-white/75">{username}</span>
  </div>
);

const ContextCard: React.FC<{
  title: string;
  icon: React.ComponentType<{ className?: string }>;
  children: React.ReactNode;
}> = ({ title, icon: Icon, children }) => (
  <section className="card-cinema p-5">
    <div className="mb-5 flex items-center gap-3">
      <Icon className="h-5 w-5 text-cinema-400" />
      <h2 className="text-lg font-semibold text-white">{title}</h2>
    </div>
    {children}
  </section>
);

const SpySignalsResults: React.FC<SpySignalsResultsProps> = ({
  groupSignals,
  gapDays,
  selectedProfileCount,
}) => {
  const summary = groupSignals.summary;
  const events = eventsForGap(groupSignals, gapDays);
  const [visibleCount, setVisibleCount] = useState(20);

  useEffect(() => {
    setVisibleCount(20);
  }, [gapDays, groupSignals]);

  const visibleEvents = events.slice(0, visibleCount);
  const totalEventCount = summary.gap_events ?? events.length;
  const secondaryMetric = gapDays === 0
    ? {
        value: summary.same_day_pair_hits,
        title: 'Same-Day Pair Hits',
        subtitle: 'Exact-day profile pair matches',
      }
    : gapDays === 1
      ? {
          value: summary.one_day_gap_events,
          title: 'Next-Day Echoes',
          subtitle: 'Watched one calendar day apart',
        }
      : {
          value: summary.gap_events ?? events.length,
          title: '3-Day Signals',
          subtitle: 'Watched within the chosen window',
        };

  const strongestPair = summary.strongest_alignment_pair ?? groupSignals.aligned_pairs[0] ?? null;
  const mostDivisive = summary.most_divisive_title ?? groupSignals.divisive_titles[0] ?? null;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          icon={CalendarDays}
          value={summary.same_day_events}
          title="Same-Day Co-Watches"
          subtitle={`${summary.same_day_pair_hits} exact-day pair hits`}
          delay={0}
        />
        <MetricCard
          icon={Clock3}
          value={secondaryMetric.value}
          title={secondaryMetric.title}
          subtitle={secondaryMetric.subtitle}
          delay={0.05}
        />
        <MetricCard
          icon={Film}
          value={summary.shared_titles}
          title="Shared Titles"
          subtitle={`Films shared by 2+ of ${selectedProfileCount} selected profiles`}
          delay={0.1}
        />
        <MetricCard
          icon={Users}
          value={strongestPair ? (
            <>
              <span className="block truncate">{strongestPair.profiles[0]}</span>
              <span className="block truncate text-cinema-200">+ {strongestPair.profiles[1]}</span>
            </>
          ) : 'N/A'}
          valueClassName="text-lg"
          title="Strongest Pair"
          subtitle={strongestPair ? `${formatNumber(strongestPair.alignment_score)} alignment score` : 'More overlap is needed'}
          delay={0.15}
        />
      </div>

      <div className="grid gap-6 2xl:grid-cols-[minmax(0,1fr)_20rem]">
        <section className="card-cinema min-w-0 p-3 sm:p-5">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3 px-1">
            <div>
              <h2 className="text-xl font-semibold text-white">Signal Feed</h2>
              <p className="mt-1 text-xs text-white/50">
                Showing {Math.min(visibleCount, events.length)} of {totalEventCount} chronological {gapLabel(gapDays)} {totalEventCount === 1 ? 'match' : 'matches'}
              </p>
            </div>
            <span className="rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-xs text-white/55">
              Most recent first
            </span>
          </div>

          <p className="mb-4 rounded-lg border border-white/10 bg-white/[0.025] px-3 py-2 text-xs leading-5 text-white/45">
            Coverage note: profiles with an authoritative diary use occurrence-level watch history; other profiles fall back to one stored date per title.
          </p>

          {events.length > 0 ? (
            <div className="space-y-2.5">
              {visibleEvents.map((event, index) => (
                <SignalEventCard key={eventKey(event)} event={event} index={index} />
              ))}
              {visibleCount < events.length && (
                <button
                  type="button"
                  onClick={() => setVisibleCount((count) => count + 20)}
                  className="btn-secondary mx-auto mt-4 flex px-5 py-2 text-sm"
                >
                  Show More Signals
                </button>
              )}
            </div>
          ) : (
            <div className="flex min-h-72 flex-col items-center justify-center rounded-xl border border-dashed border-white/15 bg-white/[0.025] px-6 text-center">
              <span className="rounded-2xl border border-cinema-400/25 bg-cinema-500/10 p-4 text-cinema-400">
                <Radar className="h-8 w-8" />
              </span>
              <h3 className="mt-5 text-lg font-semibold text-white">No signals in this window</h3>
              <p className="mt-2 max-w-sm text-sm leading-6 text-white/50">
                Try selecting more profiles or widening the time gap to uncover nearby watches.
              </p>
            </div>
          )}
        </section>

        <aside className="space-y-6">
          <StrongestPairCard pair={strongestPair} gapDays={gapDays} />
          <MostDivisiveCard movie={mostDivisive} />
        </aside>
      </div>
    </div>
  );
};

export default SpySignalsResults;
