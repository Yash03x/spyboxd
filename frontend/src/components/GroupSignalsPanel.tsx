'use client';

import React from 'react';
import { motion } from 'framer-motion';
import { Award, Calendar, Film, Users } from 'lucide-react';

import type {
  GroupSignalEvent,
  GroupSignalFollowPath,
  GroupSignalMovie,
  GroupSignalPair,
  GroupSignals,
} from '../services/api';
import StatsCard from './Charts/StatsCard';

interface GroupSignalsPanelProps {
  groupSignals: GroupSignals | null | undefined;
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

function formatDateWindow(startDate: string, endDate: string): string {
  if (startDate === endDate) {
    return formatDate(startDate);
  }
  return `${formatDate(startDate)} to ${formatDate(endDate)}`;
}

function formatMovie(title: string, year: number | null): string {
  return year ? `${title} (${year})` : title;
}

function formatOptionalNumber(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) {
    return 'n/a';
  }
  return value.toFixed(digits);
}

const SignalPanel: React.FC<{
  title: string;
  subtitle: string;
  delay: number;
  children: React.ReactNode;
}> = ({ title, subtitle, delay, children }) => (
  <motion.div
    className="card-cinema h-full"
    initial={{ opacity: 0, y: 20 }}
    animate={{ opacity: 1, y: 0 }}
    transition={{ delay, duration: 0.5 }}
  >
    <div className="mb-5">
      <h3 className="text-lg font-semibold text-white">{title}</h3>
      <p className="mt-1 text-sm text-white/60">{subtitle}</p>
    </div>
    <div className="space-y-3">{children}</div>
  </motion.div>
);

const EmptySignalState: React.FC<{ message: string }> = ({ message }) => (
  <div className="rounded-2xl border border-dashed border-white/10 bg-white/5 px-4 py-5 text-sm text-white/50">
    {message}
  </div>
);

const EventList: React.FC<{ events: GroupSignalEvent[]; emptyMessage: string }> = ({
  events,
  emptyMessage,
}) => {
  if (!events.length) {
    return <EmptySignalState message={emptyMessage} />;
  }

  return (
    <>
      {events.map((event) => (
        <div key={`${event.title}-${event.start_date}-${event.end_date}`} className="rounded-2xl border border-white/10 bg-white/5 p-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="font-medium text-white">{formatMovie(event.title, event.year)}</p>
              <p className="mt-1 text-xs text-white/60">
                {formatDateWindow(event.start_date, event.end_date)} / {event.profile_count} profiles / {event.pair_count} pair hits
              </p>
            </div>
            {event.average_rating !== null && (
              <div className="rounded-lg border border-cinema-400/20 bg-cinema-500/10 px-3 py-1 text-xs font-medium text-cinema-300">
                {formatOptionalNumber(event.average_rating, 1)} avg
              </div>
            )}
          </div>
          <p className="mt-3 text-sm text-white/70">
            {event.participants
              .map((participant) => {
                const ratingLabel = participant.rating !== null ? ` (${formatOptionalNumber(participant.rating, 1)})` : '';
                return `${participant.username}${ratingLabel}`;
              })
              .join(', ')}
          </p>
        </div>
      ))}
    </>
  );
};

const MovieList: React.FC<{
  items: GroupSignalMovie[];
  emptyMessage: string;
  footerLabel: (item: GroupSignalMovie) => string;
}> = ({ items, emptyMessage, footerLabel }) => {
  if (!items.length) {
    return <EmptySignalState message={emptyMessage} />;
  }

  return (
    <>
      {items.map((item) => (
        <div key={`${item.title}-${item.year ?? 'na'}`} className="rounded-2xl border border-white/10 bg-white/5 p-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="font-medium text-white">{formatMovie(item.title, item.year)}</p>
              <p className="mt-1 text-xs text-white/60">
                {item.profile_count} profiles / {item.rating_count} ratings / {footerLabel(item)}
              </p>
            </div>
            {item.average_rating !== null && (
              <div className="rounded-lg border border-cinema-400/20 bg-cinema-500/10 px-3 py-1 text-xs font-medium text-cinema-300">
                {formatOptionalNumber(item.average_rating, 1)} avg
              </div>
            )}
          </div>
          <p className="mt-3 text-sm text-white/70">{item.profiles.join(', ')}</p>
        </div>
      ))}
    </>
  );
};

const PairList: React.FC<{ pairs: GroupSignalPair[]; emptyMessage: string }> = ({
  pairs,
  emptyMessage,
}) => {
  if (!pairs.length) {
    return <EmptySignalState message={emptyMessage} />;
  }

  return (
    <>
      {pairs.map((pair) => (
        <div key={pair.profiles.join('-')} className="rounded-2xl border border-white/10 bg-white/5 p-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="font-medium text-white">{pair.profiles.join(' + ')}</p>
              <p className="mt-1 text-xs text-white/60">
                {pair.shared_titles} shared titles / {pair.tight_window_count} tight-window overlaps / corr {formatOptionalNumber(pair.rating_correlation)}
              </p>
            </div>
            <div className="rounded-lg border border-cinema-400/20 bg-cinema-500/10 px-3 py-1 text-xs font-medium text-cinema-300">
              {formatOptionalNumber(pair.alignment_score, 1)} score
            </div>
          </div>
          <p className="mt-3 text-sm text-white/70">
            Same day {pair.same_day_count} / 1-day gap {pair.one_day_gap_count} / rating gap {formatOptionalNumber(pair.average_rating_gap)}
          </p>
          {pair.sample_titles.length > 0 && (
            <p className="mt-2 text-xs text-white/50">
              Signals from {pair.sample_titles.map((title) => formatMovie(title.title, title.year)).join(', ')}
            </p>
          )}
        </div>
      ))}
    </>
  );
};

const FollowPathList: React.FC<{ paths: GroupSignalFollowPath[]; emptyMessage: string }> = ({
  paths,
  emptyMessage,
}) => {
  if (!paths.length) {
    return <EmptySignalState message={emptyMessage} />;
  }

  return (
    <>
      {paths.map((path) => (
        <div key={`${path.leader}-${path.follower}`} className="rounded-2xl border border-white/10 bg-white/5 p-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="font-medium text-white">
                {path.leader} then {path.follower}
              </p>
              <p className="mt-1 text-xs text-white/60">
                {path.next_day_overlap_count} next-day follow-on watches
              </p>
            </div>
          </div>
          {path.sample_titles.length > 0 && (
            <p className="mt-3 text-sm text-white/70">
              Seen on {path.sample_titles.map((title) => formatMovie(title.title, title.year)).join(', ')}
            </p>
          )}
        </div>
      ))}
    </>
  );
};

const GroupSignalsPanel: React.FC<GroupSignalsPanelProps> = ({ groupSignals }) => {
  if (!groupSignals) {
    return null;
  }

  const summary = groupSignals.summary;
  const strongestPair = summary.strongest_alignment_pair;
  const mostSharedTitle = summary.most_shared_title;
  const mostDivisiveTitle = summary.most_divisive_title;

  return (
    <motion.section
      className="space-y-8"
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.85, duration: 0.6 }}
    >
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h2 className="text-2xl font-bold text-white">Group Signals</h2>
          <p className="mt-2 max-w-3xl text-sm text-white/60">
            Spyboxd signals that flag coordinated viewing, tight taste overlap, consensus favorites, and titles that split the room.
          </p>
        </div>
        <div className="text-sm text-white/50">
          {mostSharedTitle && <p>Most shared title: {formatMovie(mostSharedTitle.title, mostSharedTitle.year)}</p>}
          {mostDivisiveTitle && <p>Most divisive title: {formatMovie(mostDivisiveTitle.title, mostDivisiveTitle.year)}</p>}
        </div>
      </div>

      {summary.profiles_analyzed < 2 ? (
        <div className="card-cinema">
          <p className="text-white/70">
            Add at least two completed profiles to unlock co-watch and correlation signals.
          </p>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-6 md:grid-cols-2 xl:grid-cols-4">
            <StatsCard
              title="Same-Day Co-Watches"
              value={summary.same_day_events}
              subtitle={`${summary.same_day_pair_hits} pair hits across diary matches`}
              icon={Users}
              gradient="from-orange-500/20 to-red-600/10"
              delay={0}
            />
            <StatsCard
              title="24h Echoes"
              value={summary.one_day_gap_events}
              subtitle={`${summary.one_day_gap_pair_hits} adjacent-day overlaps`}
              icon={Calendar}
              gradient="from-blue-500/20 to-cyan-600/10"
              delay={0.1}
            />
            <StatsCard
              title="Shared Titles"
              value={summary.shared_titles}
              subtitle={`${summary.profiles_with_diary_dates} profiles with usable diary dates`}
              icon={Film}
              gradient="from-violet-500/20 to-fuchsia-600/10"
              delay={0.2}
            />
            <StatsCard
              title="Tightest Pair"
              value={strongestPair ? strongestPair.profiles.join(' + ') : 'N/A'}
              subtitle={
                strongestPair
                  ? `${formatOptionalNumber(strongestPair.alignment_score, 1)} score across ${strongestPair.shared_titles} shared titles`
                  : 'Need overlapping ratings to score alignment'
              }
              icon={Award}
              gradient="from-emerald-500/20 to-teal-600/10"
              delay={0.3}
            />
          </div>

          <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
            <SignalPanel
              title="Same-Day Alerts"
              subtitle="Films watched on the exact same day by multiple monitored profiles."
              delay={0}
            >
              <EventList
                events={groupSignals.same_day_events}
                emptyMessage="No exact same-day co-watch events found yet."
              />
            </SignalPanel>
            <SignalPanel
              title="24h Echoes"
              subtitle="Films watched within a one-day gap, useful for spotting near-synchronous behavior."
              delay={0.05}
            >
              <EventList
                events={groupSignals.one_day_gap_events}
                emptyMessage="No one-day-gap echoes found yet."
              />
            </SignalPanel>
            <SignalPanel
              title="Aligned Pairs"
              subtitle="Pairs ranked by overlap, timing proximity, and rating similarity."
              delay={0.1}
            >
              <PairList
                pairs={groupSignals.aligned_pairs}
                emptyMessage="No pair alignment scores available yet."
              />
            </SignalPanel>
            <SignalPanel
              title="Most Shared Titles"
              subtitle="The titles that travel furthest across the monitored community."
              delay={0.15}
            >
              <MovieList
                items={groupSignals.most_shared_titles}
                emptyMessage="No shared titles across profiles yet."
                footerLabel={(item) => `stddev ${formatOptionalNumber(item.rating_stddev)}`}
              />
            </SignalPanel>
            <SignalPanel
              title="Consensus Hits"
              subtitle="Shared watches with strong average ratings and relatively low disagreement."
              delay={0.2}
            >
              <MovieList
                items={groupSignals.consensus_hits}
                emptyMessage="No consensus titles available yet."
                footerLabel={(item) => `stddev ${formatOptionalNumber(item.rating_stddev)}`}
              />
            </SignalPanel>
            <SignalPanel
              title="Divisive Titles"
              subtitle="Shared watches with the widest spread in opinion."
              delay={0.25}
            >
              <MovieList
                items={groupSignals.divisive_titles}
                emptyMessage="No divisive shared titles available yet."
                footerLabel={(item) => `gap ${formatOptionalNumber(item.max_rating_gap)}`}
              />
            </SignalPanel>
          </div>

          <SignalPanel
            title="Follow Paths"
            subtitle="Directional watch patterns where one profile tends to watch a title the day after another."
            delay={0.3}
          >
            <FollowPathList
              paths={groupSignals.follow_paths}
              emptyMessage="No clear next-day follow paths found yet."
            />
          </SignalPanel>
        </>
      )}
    </motion.section>
  );
};

export default GroupSignalsPanel;
