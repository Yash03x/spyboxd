'use client';

import React, { useMemo, useState } from 'react';
import {
  ArrowLeft,
  ArrowRight,
  CalendarDays,
  CheckCircle2,
  Clock3,
  Dna,
  Film,
  Heart,
  Info,
  Sparkles,
  Star,
  Users,
  Zap,
} from 'lucide-react';

import type {
  FeatureCoverage,
  PairDossierResponse,
  PairMovieComparison,
  SignalCalendarBucket,
  SignalCalendarResponse,
  TasteDimension,
  TasteDnaResponse,
  TasteTrait,
} from '../../services/api';
import {
  CoverageBanner,
  FeatureState,
  formatCalendarDate,
  MoviePoster,
  ProfileAvatar,
} from './InsightUI';

function numberOrDash(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return digits > 0 ? value.toFixed(digits) : Math.round(value).toLocaleString();
}

function MetricStrip({ metrics }: {
  metrics: Array<{
    label: string;
    value: React.ReactNode;
    detail: React.ReactNode;
    accent?: boolean;
  }>;
}) {
  return (
    <section className="grid overflow-hidden rounded-xl border border-white/12 bg-white/[0.025] sm:grid-cols-2 xl:grid-cols-4">
      {metrics.map((metric, index) => (
        <div key={metric.label} className={`min-w-0 px-5 py-4 ${index > 0 ? 'border-t border-white/10 sm:border-t-0 sm:border-l' : ''} ${index === 2 ? 'sm:border-l-0 xl:border-l' : ''}`}>
          <p className="text-xs font-medium text-white/55">{metric.label}</p>
          <p className={`mt-1 text-2xl font-bold ${metric.accent ? 'text-cinema-400' : 'text-white'}`}>{metric.value}</p>
          <div className="mt-1 text-xs text-white/45">{metric.detail}</div>
        </div>
      ))}
    </section>
  );
}
function PairComparisonTable({ title, rows, tone }: {
  title: string;
  rows: PairMovieComparison[];
  tone: 'love' | 'split';
}) {
  return (
    <section className="min-w-0 rounded-xl border border-white/12 bg-white/[0.02]">
      <div className="flex items-center justify-between border-b border-white/10 px-4 py-3">
        <h3 className="flex items-center gap-2 text-sm font-semibold text-white">
          {tone === 'love' ? <Heart className="h-4 w-4 text-emerald-400" /> : <Zap className="h-4 w-4 text-cinema-400" />}
          {title}
        </h3>
        <span className="text-xs text-white/35">{rows.length} titles</span>
      </div>
      {rows.length === 0 ? (
        <p className="px-4 py-8 text-center text-sm text-white/40">Not enough shared ratings yet.</p>
      ) : (
        <div className="divide-y divide-white/[0.07]">
          {rows.slice(0, 6).map((row) => (
            <div key={`${row.movie.movie_id ?? row.movie.title}-${row.movie.year ?? ''}`} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-4 px-4 py-3">
              <div className="flex min-w-0 items-center gap-3">
                <MoviePoster movie={row.movie} className="h-11 w-8" />
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-white/85">{row.movie.title}</p>
                  <p className="text-xs text-white/35">{row.movie.year ?? 'Year unknown'}</p>
                </div>
              </div>
              <div className="flex items-center gap-3">
                {row.observations.slice(0, 2).map((observation) => (
                  <span key={observation.username} className="flex items-center gap-1 text-xs font-semibold text-white/65">
                    <ProfileAvatar username={observation.username} size="sm" />
                    {observation.rating !== null ? observation.rating.toFixed(1) : '—'}
                  </span>
                ))}
                <span className={`min-w-8 text-right text-sm font-semibold ${tone === 'love' ? 'text-emerald-400' : 'text-cinema-400'}`}>
                  {row.rating_gap !== null ? row.rating_gap.toFixed(1) : '—'}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function PairTimeline({ data }: { data: PairDossierResponse }) {
  const paths = data.influence_paths ?? [];
  return (
    <section className="rounded-xl border border-white/12 bg-white/[0.02]">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 px-4 py-3">
        <h3 className="flex items-center gap-2 text-sm font-semibold text-white">
          <Clock3 className="h-4 w-4 text-cinema-400" />
          Who watched first?
          <span className="font-normal text-white/40">Follow patterns</span>
        </h3>
        <span className="text-xs text-white/35">Sequence is not proof of influence</span>
      </div>
      {paths.length === 0 ? (
        <p className="px-4 py-10 text-center text-sm text-white/40">No directional watch pattern is available for this pair.</p>
      ) : (
        <div className="divide-y divide-white/[0.06] px-4">
          {paths.slice(0, 8).map((path, index) => (
            <div key={`${path.movie.title}-${path.leader_date}-${index}`} className="grid gap-3 py-3 sm:grid-cols-[minmax(0,1fr)_3rem_minmax(0,1fr)] sm:items-center">
              <div className="flex min-w-0 items-center gap-2 sm:justify-end">
                <span className="text-xs text-white/40">{formatCalendarDate(path.leader_date)}</span>
                <ProfileAvatar username={path.leader} size="sm" />
                <span className="truncate text-xs font-semibold text-white/70">{path.leader}</span>
              </div>
              <div className="flex items-center justify-center gap-2 text-cinema-400">
                <ArrowRight className="h-5 w-5" />
                <span className="sr-only">watched before</span>
              </div>
              <div className="flex min-w-0 items-center gap-2">
                <MoviePoster movie={path.movie} className="h-10 w-7" />
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-white/85">{path.movie.title}</p>
                  <p className="text-xs text-white/40">{path.follower} · {formatCalendarDate(path.follower_date)} · {path.gap_days}d later</p>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

export function PairDossierPanel({ data, coverage }: {
  data?: PairDossierResponse;
  coverage?: FeatureCoverage;
}) {
  const effectiveCoverage = data?.coverage ?? coverage;
  if (!data) {
    return (
      <div className="space-y-4">
        {effectiveCoverage && <CoverageBanner coverage={effectiveCoverage} />}
        <FeatureState
          title={effectiveCoverage?.status === 'blocked' ? 'Pair Dossier needs more watch history' : 'Pair Dossier is unavailable'}
          message={effectiveCoverage?.blockers?.[0] ?? 'The comparison service did not return a dossier for this pair.'}
        />
      </div>
    );
  }

  const summary = data.summary;
  const reviewRows = [...(data.agreements ?? []), ...(data.disagreements ?? [])]
    .filter((row) => row.observations.some((observation) => observation.review_text))
    .slice(0, 1);

  return (
    <div className="space-y-4">
      <CoverageBanner coverage={data.coverage} />
      {data.coverage.status === 'blocked' ? (
        <FeatureState title="Pair Dossier is blocked" message={data.coverage.blockers[0] ?? 'Import more dated watch history for both profiles.'} />
      ) : (
        <>
          <MetricStrip metrics={[
            {
              label: 'Alignment',
              value: numberOrDash(summary.alignment_score, 1),
              detail: summary.rating_correlation !== null ? `${numberOrDash(summary.rating_correlation, 2)} rating correlation` : 'Rating correlation unavailable',
              accent: true,
            },
            { label: 'Shared films', value: numberOrDash(summary.shared_titles), detail: `${numberOrDash(summary.rated_overlap)} jointly rated` },
            { label: 'Close-watch signals', value: numberOrDash(summary.within_gap_events), detail: `${numberOrDash(summary.same_day_events)} on the same day` },
            {
              label: 'Date coverage',
              value: summary.date_coverage_ratio === null || summary.date_coverage_ratio === undefined ? `${data.coverage.score}%` : `${Math.round(summary.date_coverage_ratio * 100)}%`,
              detail: `${data.coverage.dated_watch_events.toLocaleString()} dated events`,
              accent: true,
            },
          ]} />

          <p className="flex items-start gap-2 px-1 text-xs leading-5 text-white/40">
            <Info className="mt-0.5 h-4 w-4 shrink-0" />
            Alignment reflects rating agreement, overlap, recency, and available behavior. Sequence is a follow pattern, not proof of influence.
          </p>

          <PairTimeline data={data} />

          <div className="grid gap-4 xl:grid-cols-2">
            <PairComparisonTable title="Common Loves" rows={data.agreements ?? []} tone="love" />
            <PairComparisonTable title="Biggest Disagreements" rows={data.disagreements ?? []} tone="split" />
          </div>

          {reviewRows.map((row) => (
            <section key={`${row.movie.title}-reviews`} className="rounded-xl border border-white/12 bg-white/[0.02] p-4">
              <div className="flex items-center gap-3">
                <MoviePoster movie={row.movie} className="h-14 w-10" />
                <div>
                  <h3 className="text-sm font-semibold text-white">Review Face-off</h3>
                  <p className="mt-1 text-sm text-white/55">{row.movie.title} {row.movie.year ? `(${row.movie.year})` : ''}</p>
                </div>
              </div>
              <div className="mt-4 grid gap-4 lg:grid-cols-2 lg:divide-x lg:divide-white/10">
                {row.observations.slice(0, 2).map((observation, index) => (
                  <blockquote key={observation.username} className={index > 0 ? 'lg:pl-4' : ''}>
                    <div className="flex items-center gap-2">
                      <ProfileAvatar username={observation.username} size="sm" />
                      <span className="text-xs font-semibold text-white/75">{observation.username}</span>
                      {observation.rating !== null && <span className="text-xs text-cinema-300">{observation.rating.toFixed(1)} ★</span>}
                    </div>
                    <p className="mt-2 line-clamp-3 text-sm leading-6 text-white/55">{observation.review_text}</p>
                  </blockquote>
                ))}
              </div>
            </section>
          ))}
        </>
      )}
    </div>
  );
}

const DIMENSION_LABELS: Record<TasteDimension, string> = {
  genre: 'Genres',
  director: 'Directors',
  actor: 'Actors',
  language: 'Languages',
  country: 'Countries',
  decade: 'Decades',
  keyword: 'Keywords',
  runtime: 'Runtime bands',
};

function TraitMirror({ trait, profiles }: { trait: TasteTrait; profiles: string[] }) {
  const left = trait.per_profile.find((score) => score.username === profiles[0]);
  const right = trait.per_profile.find((score) => score.username === profiles[1]);
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_4rem_minmax(0,1fr)] items-center gap-2 text-xs">
      <div className="flex items-center justify-end gap-2">
        <span className="truncate text-white/55">{left ? `${Math.round(left.score)}%` : '—'}</span>
        <span className="h-1.5 w-full max-w-28 overflow-hidden rounded-full bg-white/10">
          <span className="ml-auto block h-full rounded-full bg-cinema-500" style={{ width: `${Math.max(2, left?.score ?? 0)}%` }} />
        </span>
      </div>
      <span className="truncate text-center font-medium text-white/75" title={trait.label}>{trait.label}</span>
      <div className="flex items-center gap-2">
        <span className="h-1.5 w-full max-w-28 overflow-hidden rounded-full bg-white/10">
          <span className="block h-full rounded-full bg-blue-500" style={{ width: `${Math.max(2, right?.score ?? 0)}%` }} />
        </span>
        <span className="truncate text-white/55">{right ? `${Math.round(right.score)}%` : '—'}</span>
      </div>
    </div>
  );
}

export function TasteDnaPanel({ data, coverage, profiles }: {
  data?: TasteDnaResponse;
  coverage?: FeatureCoverage;
  profiles: string[];
}) {
  const effectiveCoverage = data?.coverage ?? coverage;
  if (!data) {
    return (
      <div className="space-y-4">
        {effectiveCoverage && <CoverageBanner coverage={effectiveCoverage} />}
        <FeatureState
          title={effectiveCoverage?.status === 'blocked' ? 'Taste DNA needs movie metadata' : 'Taste DNA is unavailable'}
          message={effectiveCoverage?.blockers?.[0] ?? 'TMDB enrichment and shared ratings are required to calculate taste traits.'}
        />
      </div>
    );
  }

  const dimensionEntries = (Object.entries(data.dimensions ?? {}) as Array<[TasteDimension, TasteTrait[]]>)
    .filter(([, traits]) => traits?.length)
    .slice(0, 6);

  return (
    <div className="space-y-4">
      <CoverageBanner coverage={data.coverage} />
      {data.coverage.status === 'blocked' ? (
        <FeatureState title="Taste DNA is blocked" message={data.coverage.blockers[0] ?? 'TMDB enrichment has not been completed for these profiles.'} />
      ) : (
        <>
          <MetricStrip metrics={[
            { label: 'Taste similarity', value: numberOrDash(data.summary.similarity_score), detail: 'Behavior and metadata match', accent: true },
            { label: 'Shared rated titles', value: numberOrDash(data.summary.shared_rated_titles), detail: 'Ratings used for comparison' },
            {
              label: 'Metadata coverage',
              value: data.summary.metadata_coverage_ratio === null ? '—' : `${Math.round(data.summary.metadata_coverage_ratio * 100)}%`,
              detail: 'TMDB-enriched titles',
            },
            {
              label: 'TMDB status',
              value: data.summary.tmdb_status === 'connected' ? 'Connected' : data.summary.tmdb_status === 'partial' ? 'Partial' : 'Unavailable',
              detail: 'Live metadata and enrichments',
            },
          ]} />

          <div className="grid gap-4 2xl:grid-cols-[minmax(0,1.25fr)_minmax(22rem,.75fr)]">
            <section className="rounded-xl border border-white/12 bg-white/[0.02] p-4">
              <div className="mb-4 flex items-center justify-between gap-3">
                <h3 className="flex items-center gap-2 text-sm font-semibold text-white"><Dna className="h-4 w-4 text-cinema-400" /> Where your tastes align</h3>
                <div className="flex items-center gap-4 text-[11px] text-white/45">
                  <span className="flex items-center gap-1"><i className="h-1.5 w-5 rounded bg-cinema-500" />{profiles[0]}</span>
                  <span className="flex items-center gap-1"><i className="h-1.5 w-5 rounded bg-blue-500" />{profiles[1]}</span>
                </div>
              </div>
              <div className="space-y-5">
                {dimensionEntries.length === 0 ? (
                  <p className="py-10 text-center text-sm text-white/40">No metadata dimensions are ready yet.</p>
                ) : dimensionEntries.map(([dimension, traits]) => (
                  <div key={dimension} className="grid gap-3 border-t border-white/[0.07] pt-4 sm:grid-cols-[7rem_minmax(0,1fr)]">
                    <div>
                      <p className="text-xs font-semibold text-white/75">{DIMENSION_LABELS[dimension]}</p>
                      <p className="mt-1 text-[11px] text-white/35">Top {Math.min(5, traits.length)}</p>
                    </div>
                    <div className="space-y-2.5">
                      {traits.slice(0, 5).map((trait) => <TraitMirror key={trait.id} trait={trait} profiles={profiles} />)}
                    </div>
                  </div>
                ))}
              </div>
            </section>

            <div className="space-y-4">
              <section className="rounded-xl border border-white/12 bg-white/[0.02]">
                <div className="border-b border-white/10 px-4 py-3">
                  <h3 className="flex items-center gap-2 text-sm font-semibold text-white"><Sparkles className="h-4 w-4 text-cinema-400" /> Strongest shared affinities</h3>
                </div>
                <div className="divide-y divide-white/[0.07]">
                  {(data.shared_signature ?? []).slice(0, 8).map((trait) => (
                    <div key={trait.id} className="grid grid-cols-[minmax(0,1fr)_auto] gap-3 px-4 py-2.5 text-sm">
                      <span className="truncate text-white/70">{trait.label}</span>
                      <span className="font-semibold text-cinema-300">{Math.round(trait.group_score)}%</span>
                    </div>
                  ))}
                  {(data.shared_signature ?? []).length === 0 && <p className="px-4 py-8 text-center text-sm text-white/40">No shared affinities available.</p>}
                </div>
              </section>

              <section className="rounded-xl border border-white/12 bg-white/[0.02] p-4">
                <h3 className="text-sm font-semibold text-white">Taste splits</h3>
                <p className="mt-1 text-xs text-white/40">Traits where these profiles lean in different directions.</p>
                <div className="mt-4 space-y-3">
                  {(data.contrasts ?? []).slice(0, 6).map((trait) => <TraitMirror key={trait.id} trait={trait} profiles={profiles} />)}
                  {(data.contrasts ?? []).length === 0 && <p className="py-5 text-center text-sm text-white/40">No strong divergence detected.</p>}
                </div>
              </section>
            </div>
          </div>

          <div className="grid gap-4 xl:grid-cols-2">
            <section className="rounded-xl border border-white/12 bg-white/[0.02] p-4">
              <h3 className="flex items-center gap-2 text-sm font-semibold text-white"><Heart className="h-4 w-4 text-cinema-400" /> Shared taste, real examples</h3>
              <div className="mt-4 flex gap-3 overflow-x-auto pb-2">
                {(data.shared_signature ?? []).flatMap((trait) => trait.top_movies ?? []).slice(0, 8).map((movie, index) => (
                  <div key={`${movie.movie_id ?? movie.title}-${index}`} className="w-24 shrink-0">
                    <MoviePoster movie={movie} className="h-32 w-24" />
                    <p className="mt-2 line-clamp-2 text-xs font-medium text-white/65">{movie.title}</p>
                  </div>
                ))}
              </div>
            </section>
            <section className="rounded-xl border border-white/12 bg-white/[0.02] p-4">
              <h3 className="flex items-center gap-2 text-sm font-semibold text-white"><Film className="h-4 w-4 text-cinema-400" /> Semantic neighbors</h3>
              <p className="mt-1 text-xs text-white/40">Contextual matches, not exact-title co-watches.</p>
              <div className="mt-4 flex gap-3 overflow-x-auto pb-2">
                {(data.semantic_neighbors ?? []).slice(0, 8).map((item) => (
                  <div key={`${item.movie.movie_id ?? item.movie.title}-${item.reason}`} className="w-24 shrink-0">
                    <MoviePoster movie={item.movie} className="h-32 w-24" />
                    <p className="mt-2 line-clamp-2 text-xs font-medium text-white/65">{item.movie.title}</p>
                    <p className="mt-1 line-clamp-2 text-[10px] text-white/35">{item.reason}</p>
                  </div>
                ))}
              </div>
            </section>
          </div>
        </>
      )}
    </div>
  );
}

function isoToUtc(value: string): Date {
  const [year, month, day] = value.split('-').map(Number);
  return new Date(Date.UTC(year, month - 1, day));
}

function utcToIso(value: Date): string {
  return value.toISOString().slice(0, 10);
}

function calendarDays(from: string, to: string, buckets: SignalCalendarBucket[]) {
  const byDate = new Map(buckets.map((bucket) => [bucket.date, bucket]));
  const start = isoToUtc(from);
  const end = isoToUtc(to);
  const days: Array<{ date: string; bucket?: SignalCalendarBucket; spacer?: boolean }> = [];
  for (let index = 0; index < start.getUTCDay(); index += 1) days.push({ date: `spacer-${index}`, spacer: true });
  for (let cursor = start; cursor <= end && days.length < 378; cursor = new Date(cursor.getTime() + 86_400_000)) {
    const date = utcToIso(cursor);
    days.push({ date, bucket: byDate.get(date) });
  }
  return days;
}

function intensityClass(intensity: number): string {
  if (intensity >= 4) return 'bg-cinema-400 ring-1 ring-cinema-300/60';
  if (intensity === 3) return 'bg-cinema-500/80';
  if (intensity === 2) return 'bg-cinema-600/55';
  if (intensity === 1) return 'bg-cinema-700/35';
  return 'bg-white/[0.055]';
}

export function SignalCalendarPanel({ data, coverage }: {
  data?: SignalCalendarResponse;
  coverage?: FeatureCoverage;
}) {
  const effectiveCoverage = data?.coverage ?? coverage;
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const days = useMemo(() => data ? calendarDays(data.from, data.to, data.buckets ?? []) : [], [data]);
  const selectedEvents = selectedDate && data
    ? (data.events ?? []).filter((event) => event.start_date <= selectedDate && event.end_date >= selectedDate)
    : [];
  const peakBucket = data?.buckets?.reduce<SignalCalendarBucket | null>((peak, bucket) => !peak || bucket.signal_count > peak.signal_count ? bucket : peak, null) ?? null;

  if (!data) {
    return (
      <div className="space-y-4">
        {effectiveCoverage && <CoverageBanner coverage={effectiveCoverage} />}
        <FeatureState
          title={effectiveCoverage?.status === 'blocked' ? 'Signal Calendar needs dated watches' : 'Signal Calendar is unavailable'}
          message={effectiveCoverage?.blockers?.[0] ?? 'No calendar aggregation was returned for this pair.'}
        />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <CoverageBanner coverage={data.coverage} />
      {data.coverage.status === 'blocked' ? (
        <FeatureState title="Signal Calendar is blocked" message={data.coverage.blockers[0] ?? 'Dated watch events are required for a calendar view.'} />
      ) : (
        <>
          <MetricStrip metrics={[
            { label: 'Signal days', value: (data.buckets ?? []).filter((bucket) => bucket.signal_count > 0).length, detail: `${formatCalendarDate(data.from)} – ${formatCalendarDate(data.to)}`, accent: true },
            { label: 'Total signals', value: (data.buckets ?? []).reduce((sum, bucket) => sum + bucket.signal_count, 0), detail: `Within ${data.gap_days} day${data.gap_days === 1 ? '' : 's'}` },
            { label: 'Pair hits', value: (data.buckets ?? []).reduce((sum, bucket) => sum + bucket.pair_hits, 0), detail: 'Profile-pair matches' },
            { label: 'Peak day', value: peakBucket ? formatCalendarDate(peakBucket.date) : '—', detail: peakBucket ? `${peakBucket.signal_count} signals` : 'No signal peak' },
          ]} />

          <section className="rounded-xl border border-white/12 bg-white/[0.02] p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="flex items-center gap-2 text-sm font-semibold text-white"><CalendarDays className="h-4 w-4 text-cinema-400" /> Signal activity</h3>
                <p className="mt-1 text-xs text-white/40">Select a highlighted day to inspect matching watches.</p>
              </div>
              <div className="flex items-center gap-1.5 text-[10px] text-white/40">
                Less
                {[0, 1, 2, 3, 4].map((level) => <i key={level} className={`h-3 w-3 rounded-[3px] ${intensityClass(level)}`} />)}
                More
              </div>
            </div>
            <div className="mt-5 overflow-x-auto pb-2">
              <div className="grid w-max grid-flow-col grid-rows-7 gap-1">
                {days.map((day) => day.spacer ? (
                  <span key={day.date} className="h-4 w-4" />
                ) : (
                  <button
                    key={day.date}
                    type="button"
                    aria-label={`${formatCalendarDate(day.date)}: ${day.bucket?.signal_count ?? 0} signals`}
                    aria-pressed={selectedDate === day.date}
                    onClick={() => setSelectedDate(day.date)}
                    className={`h-4 w-4 rounded-[3px] transition-transform hover:scale-125 focus:outline-none focus-visible:ring-2 focus-visible:ring-white ${intensityClass(day.bucket?.intensity ?? 0)} ${selectedDate === day.date ? 'ring-2 ring-white' : ''}`}
                    title={`${formatCalendarDate(day.date)} · ${day.bucket?.signal_count ?? 0} signals`}
                  />
                ))}
              </div>
            </div>
          </section>

          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
            <section className="rounded-xl border border-white/12 bg-white/[0.02]">
              <div className="border-b border-white/10 px-4 py-3">
                <h3 className="text-sm font-semibold text-white">Monthly signal rhythm</h3>
              </div>
              <div className="divide-y divide-white/[0.07]">
                {(data.monthly_summary ?? []).slice(-12).map((month) => (
                  <div key={month.month} className="grid grid-cols-[6rem_minmax(0,1fr)_auto] items-center gap-3 px-4 py-2.5">
                    <span className="text-xs text-white/50">{month.month}</span>
                    <span className="h-1.5 overflow-hidden rounded-full bg-white/[0.07]">
                      <span className="block h-full rounded-full bg-cinema-500" style={{ width: `${Math.min(100, month.signal_count * 4)}%` }} />
                    </span>
                    <span className="text-xs font-semibold text-white/70">{month.signal_count}</span>
                  </div>
                ))}
              </div>
            </section>

            <section className="rounded-xl border border-white/12 bg-white/[0.02] p-4">
              <h3 className="text-sm font-semibold text-white">{selectedDate ? formatCalendarDate(selectedDate) : 'Choose a signal day'}</h3>
              {selectedDate ? (
                selectedEvents.length > 0 ? (
                  <div className="mt-4 space-y-3">
                    {selectedEvents.slice(0, 8).map((event) => (
                      <div key={event.event_id} className="rounded-lg border border-white/10 bg-white/[0.035] p-3">
                        <p className="text-sm font-medium text-white/80">{event.title}</p>
                        <p className="mt-1 text-xs text-white/40">{event.profile_count} profiles · {event.pair_count} pair hits</p>
                      </div>
                    ))}
                  </div>
                ) : <p className="mt-3 text-sm leading-6 text-white/40">No detailed event was returned for this date.</p>
              ) : <p className="mt-3 text-sm leading-6 text-white/40">The calendar keeps the full year visible while details stay focused on one day.</p>}
            </section>
          </div>
        </>
      )}
    </div>
  );
}
