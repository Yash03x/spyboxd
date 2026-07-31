'use client';

import React, { useMemo, useState } from 'react';
import { CalendarRange, Dna, Info, Star, TrendingUp } from 'lucide-react';

import type { FeatureCoverage, TasteTimelinePoint, TasteTimelineResponse } from '../../services/api';
import { CoverageBanner, FeatureState } from './InsightUI';

type TimelineGrain = 'yearly' | 'seasonal';

function percent(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : `${Math.round(value * 100)}%`;
}

function rating(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : value.toFixed(2);
}

function latestSharedGap(points: TasteTimelinePoint[]): number | null {
  for (let index = points.length - 1; index >= 0; index -= 1) {
    const ratings = points[index].per_profile
      .map((profile) => profile.average_rating)
      .filter((value): value is number => value !== null);
    if (ratings.length >= 2) return Math.abs(ratings[0] - ratings[1]);
  }
  return null;
}

function RatingTrend({ points, profiles }: { points: TasteTimelinePoint[]; profiles: string[] }) {
  const plotted = points.slice(-16);
  const width = 920;
  const height = 240;
  const inset = { left: 42, right: 18, top: 18, bottom: 34 };
  const chartWidth = width - inset.left - inset.right;
  const chartHeight = height - inset.top - inset.bottom;
  const colors = ['#f57c00', '#3b82f6'];
  const x = (index: number) => inset.left + (plotted.length <= 1 ? chartWidth / 2 : (index / (plotted.length - 1)) * chartWidth);
  const y = (value: number) => inset.top + ((5 - Math.max(0, Math.min(5, value))) / 5) * chartHeight;
  const profileLines = profiles.slice(0, 2).map((username) => ({
    username,
    points: plotted.flatMap((period, index) => {
      const value = period.per_profile.find((profile) => profile.username === username)?.average_rating;
      return value === null || value === undefined ? [] : [{ x: x(index), y: y(value), value }];
    }),
  }));

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold text-white"><TrendingUp className="h-4 w-4 text-cinema-400" /> Average rating through time</h3>
          <p className="mt-1 text-xs text-white/40">A behavioral trend, not a claim that either profile caused the other to change.</p>
        </div>
        <div className="flex items-center gap-4 text-[11px] text-white/50">
          {profiles.slice(0, 2).map((username, index) => (
            <span key={username} className="flex items-center gap-1.5"><i className="h-1.5 w-5 rounded-full" style={{ backgroundColor: colors[index] }} />{username}</span>
          ))}
        </div>
      </div>
      <div className="mt-4 overflow-x-auto">
        <svg viewBox={`0 0 ${width} ${height}`} className="h-60 min-w-[42rem] w-full" role="img" aria-label="Average ratings by period for the selected profiles">
          {[0, 1, 2, 3, 4, 5].map((tick) => {
            const lineY = y(tick);
            return (
              <g key={tick}>
                <line x1={inset.left} x2={width - inset.right} y1={lineY} y2={lineY} stroke="rgba(255,255,255,.07)" />
                <text x={inset.left - 10} y={lineY + 4} textAnchor="end" fill="rgba(255,255,255,.35)" fontSize="10">{tick}</text>
              </g>
            );
          })}
          {plotted.map((period, index) => (
            <text key={period.key} x={x(index)} y={height - 10} textAnchor="middle" fill="rgba(255,255,255,.35)" fontSize="9">
              {plotted.length > 10 && index % 2 !== 0 ? '' : period.label}
            </text>
          ))}
          {profileLines.map((line, index) => (
            <g key={line.username}>
              {line.points.length > 1 && (
                <polyline
                  points={line.points.map((point) => `${point.x},${point.y}`).join(' ')}
                  fill="none"
                  stroke={colors[index]}
                  strokeWidth="3"
                  strokeLinejoin="round"
                  strokeLinecap="round"
                />
              )}
              {line.points.map((point, pointIndex) => (
                <circle key={`${line.username}-${pointIndex}`} cx={point.x} cy={point.y} r="4" fill={colors[index]} stroke="#111827" strokeWidth="2">
                  <title>{line.username}: {point.value.toFixed(2)}</title>
                </circle>
              ))}
            </g>
          ))}
        </svg>
      </div>
    </div>
  );
}

export default function TasteTimelinePanel({ data, coverage }: {
  data?: TasteTimelineResponse;
  coverage?: FeatureCoverage;
}) {
  const [grain, setGrain] = useState<TimelineGrain>('yearly');
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const effectiveCoverage = data?.coverage ?? coverage;
  const periods = useMemo(() => data ? (grain === 'yearly' ? data.yearly : data.seasonal) ?? [] : [], [data, grain]);
  const selectedPeriod = periods.find((period) => period.key === selectedKey) ?? periods.at(-1) ?? null;

  if (!data) {
    return (
      <div className="space-y-4">
        {effectiveCoverage && <CoverageBanner coverage={effectiveCoverage} />}
        <FeatureState
          title={effectiveCoverage?.status === 'blocked' ? 'Taste Through Time needs dated watches' : 'Taste Through Time is unavailable'}
          message={effectiveCoverage?.blockers?.[0] ?? 'No dated taste timeline was returned for this pair.'}
        />
      </div>
    );
  }

  if (data.coverage.status === 'blocked') {
    return <div className="space-y-4"><CoverageBanner coverage={data.coverage} /><FeatureState title="Taste Through Time is blocked" message={data.coverage.blockers[0] ?? 'Dated watch events are required for this view.'} /></div>;
  }

  const latestGap = latestSharedGap(periods);

  return (
    <div className="space-y-4">
      <CoverageBanner coverage={data.coverage} />
      <section className="grid overflow-hidden panel-insight sm:grid-cols-2 xl:grid-cols-4">
        {[
          { label: 'Observed years', value: data.summary.years, detail: data.summary.first_year && data.summary.last_year ? `${data.summary.first_year}–${data.summary.last_year}` : 'No dated range' },
          { label: 'Date coverage', value: percent(data.summary.date_coverage_ratio), detail: `${data.summary.dated_watch_events.toLocaleString()} dated events` },
          { label: 'Rating coverage', value: percent(data.summary.rating_coverage_ratio), detail: `${data.summary.rated_dated_events.toLocaleString()} dated ratings` },
          { label: 'Latest avg rating gap', value: rating(latestGap), detail: 'Profile averages, not title-level agreement' },
        ].map((metric, index) => (
          <div key={metric.label} className={`px-5 py-4 ${index > 0 ? 'border-t border-white/10 sm:border-l sm:border-t-0' : ''} ${index === 2 ? 'sm:border-l-0 xl:border-l' : ''}`}>
            <p className="text-xs font-medium text-white/55">{metric.label}</p>
            <p className={`mt-1 text-2xl font-bold ${index === 1 ? 'text-cinema-400' : 'text-white'}`}>{metric.value}</p>
            <p className="mt-1 text-xs text-white/40">{metric.detail}</p>
          </div>
        ))}
      </section>

      <p className="flex items-start gap-2 px-1 text-xs leading-5 text-white/40">
        <Info className="mt-0.5 h-4 w-4 shrink-0" /> Only observed, dated watch events are placed on the timeline. {data.summary.undated_known_watches.toLocaleString()} known watches without dates remain excluded.
      </p>

      <section className="panel-insight p-4">
        <div className="mb-4 flex justify-end">
          <div className="flex rounded-lg border border-white/10 bg-black/15 p-1" aria-label="Timeline detail">
            {(['yearly', 'seasonal'] as TimelineGrain[]).map((value) => (
              <button key={value} type="button" aria-pressed={grain === value} onClick={() => { setGrain(value); setSelectedKey(null); }} className={`rounded-md px-3 py-1.5 text-xs font-semibold capitalize ${grain === value ? 'bg-cinema-500/15 text-cinema-300 ring-1 ring-cinema-400/35' : 'text-white/45 hover:text-white'}`}>
                {value}
              </button>
            ))}
          </div>
        </div>
        {periods.length > 0 ? <RatingTrend points={periods} profiles={data.selected_profiles} /> : <FeatureState title="No dated periods" message="This selection has no dated events for the requested timeline grain." />}
      </section>

      {periods.length > 0 && (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.3fr)_22rem]">
          <section className="overflow-hidden panel-insight">
            <div className="border-b border-white/10 px-4 py-3">
              <h3 className="flex items-center gap-2 text-sm font-semibold text-white"><CalendarRange className="h-4 w-4 text-cinema-400" /> Period details</h3>
            </div>
            <div className="max-h-96 divide-y divide-white/[0.07] overflow-y-auto [content-visibility:auto]">
              {[...periods].reverse().map((period) => (
                <button key={period.key} type="button" aria-pressed={selectedPeriod?.key === period.key} onClick={() => setSelectedKey(period.key)} className={`grid w-full grid-cols-[5.5rem_minmax(0,1fr)_4rem] items-center gap-3 px-4 py-3 text-left ${selectedPeriod?.key === period.key ? 'bg-cinema-500/[0.08]' : 'hover:bg-white/[0.03]'}`}>
                  <span className="text-xs font-semibold text-white/65">{period.label}</span>
                  <span className="flex min-w-0 gap-4">
                    {period.per_profile.slice(0, 2).map((profile, index) => (
                      <span key={profile.username} className="min-w-0 truncate text-xs text-white/45"><i className={`mr-1.5 inline-block h-1.5 w-1.5 rounded-full ${index === 0 ? 'bg-cinema-500' : 'bg-blue-500'}`} />{rating(profile.average_rating)} avg · {profile.watch_events} watches</span>
                    ))}
                  </span>
                  <span className="text-right text-xs font-semibold text-white/60">{period.unique_films}</span>
                </button>
              ))}
            </div>
          </section>

          <aside className="panel-insight p-4">
            <h3 className="flex items-center gap-2 text-sm font-semibold text-white"><Dna className="h-4 w-4 text-cinema-400" /> {selectedPeriod?.label ?? 'Period'} signals</h3>
            <p className="mt-1 text-xs text-white/40">Most observed metadata traits in this period.</p>
            <div className="mt-4 space-y-2.5">
              {(selectedPeriod?.top_traits ?? []).slice(0, 8).map((trait) => (
                <div key={`${trait.dimension}-${trait.label}`} className="flex items-center justify-between gap-3 rounded-lg border border-white/[0.07] bg-white/[0.025] px-3 py-2">
                  <span className="min-w-0 truncate text-xs text-white/65">{trait.label}</span>
                  <span className="flex shrink-0 items-center gap-1 text-[11px] text-white/40"><Star className="h-3 w-3 text-cinema-400" />{rating(trait.average_rating)} · {trait.watch_events}</span>
                </div>
              ))}
              {(selectedPeriod?.top_traits ?? []).length === 0 && <p className="py-8 text-center text-sm text-white/40">No enriched traits for this period.</p>}
            </div>
          </aside>
        </div>
      )}
    </div>
  );
}
