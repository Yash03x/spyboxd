'use client';

import React, { useState } from 'react';
import { ArrowRight, History, RefreshCw, Repeat2 } from 'lucide-react';

import type { RewatchEcho, RewatchEchoesResponse } from '../../services/api';
import { CoverageBanner, FeatureState, formatCalendarDate, MoviePoster, ProfileAvatar } from './InsightUI';

function echoLabel(echo: RewatchEcho): string {
  if (echo.pattern === 'rewatch_plus_rewatch') return 'Both revisited it';
  return 'First watch met a rewatch';
}

function echoExplanation(echo: RewatchEcho): string {
  if (echo.pattern === 'rewatch_plus_rewatch') return 'Every matched event is an observed rewatch.';
  return 'At least one observed rewatch overlaps a first-known watch.';
}

function EchoRow({ echo }: { echo: RewatchEcho }) {
  const participants = echo.participants ?? [];
  return (
    <article className="grid gap-3 border-t border-white/[0.07] px-4 py-3 first:border-t-0 lg:grid-cols-[minmax(12rem,1.1fr)_minmax(0,1.6fr)_auto] lg:items-center">
      <div className="flex min-w-0 items-center gap-3">
        <MoviePoster movie={echo.movie} className="h-14 w-10" />
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-white/85">{echo.movie.title}</p>
          <p className="mt-1 text-xs text-white/40">{echo.movie.year ?? 'Year unknown'} · {echoLabel(echo)}</p>
        </div>
      </div>

      <div className="flex min-w-0 flex-wrap items-center gap-2">
        {participants.map((participant, index) => (
          <React.Fragment key={`${participant.username}-${participant.watched_date ?? index}`}>
            {index > 0 && <ArrowRight className="h-4 w-4 shrink-0 text-cinema-400" aria-hidden="true" />}
            <div className="flex min-w-0 items-center gap-2 rounded-lg border border-white/10 bg-white/[0.025] px-2.5 py-2">
              <ProfileAvatar username={participant.username} size="sm" />
              <div className="min-w-0">
                <p className="max-w-32 truncate text-xs font-semibold text-white/75">{participant.username}</p>
                <p className="mt-0.5 text-[10px] text-white/40">
                  {formatCalendarDate(participant.watched_date)} · {participant.is_rewatch ? 'Rewatch' : 'First known watch'}
                </p>
              </div>
            </div>
          </React.Fragment>
        ))}
      </div>

      <div className="text-left lg:max-w-52 lg:text-right">
        <p className="text-xs font-semibold text-cinema-300">
          {echo.day_gap === 0 ? 'Same day' : `${echo.day_gap} day${echo.day_gap === 1 ? '' : 's'} apart`}
        </p>
        <p className="mt-1 line-clamp-2 text-[11px] leading-4 text-white/40">{echoExplanation(echo)}</p>
      </div>
    </article>
  );
}

export default function RewatchEchoesPanel({
  data,
  loading,
  error,
  onRetry,
}: {
  data?: RewatchEchoesResponse;
  loading: boolean;
  error: boolean;
  onRetry: () => void;
}) {
  const [expanded, setExpanded] = useState(false);

  if (loading) {
    return <FeatureState title="Finding rewatch echoes" message="Matching revisits against first-known watches in the selected time window." loading />;
  }

  if (error || !data) {
    return (
      <section className="panel-insight px-5 py-8 text-center">
        <History className="mx-auto h-7 w-7 text-cinema-400" />
        <h2 className="mt-3 text-base font-semibold text-white">Rewatch Echoes are unavailable</h2>
        <p className="mx-auto mt-2 max-w-xl text-sm leading-6 text-white/45">
          Existing Spy Signals still work. This additional view needs occurrence-level rewatch history for the selected profiles.
        </p>
        <button type="button" onClick={onRetry} className="btn-secondary mx-auto mt-4 flex items-center gap-2 px-4 py-2 text-xs">
          <RefreshCw className="h-3.5 w-3.5" /> Try again
        </button>
      </section>
    );
  }

  const echoes = data.echoes ?? [];
  const visibleEchoes = expanded ? echoes : echoes.slice(0, 6);

  return (
    <section className="space-y-4" aria-labelledby="rewatch-echoes-title">
      <CoverageBanner coverage={data.coverage} />
      <div className="overflow-hidden panel-insight">
        <header className="flex flex-col gap-3 border-b border-white/10 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 id="rewatch-echoes-title" className="flex items-center gap-2 text-base font-semibold text-white">
              <Repeat2 className="h-4 w-4 text-cinema-400" /> Rewatch Echoes
            </h2>
            <p className="mt-1 text-xs leading-5 text-white/40">
              First-known watches and revisits that happened together or soon after. Missing historical dates are never inferred.
            </p>
          </div>
          <div className="flex shrink-0 gap-4 text-right">
            <div>
              <p className="text-lg font-bold text-white">{data.summary.echoes}</p>
              <p className="text-[10px] text-white/40">echoes</p>
            </div>
            <div>
              <p className="text-lg font-bold text-cinema-300">{data.summary.rewatch_plus_rewatch}</p>
              <p className="text-[10px] text-white/40">shared revisits</p>
            </div>
          </div>
        </header>

        {data.coverage.status === 'blocked' ? (
          <FeatureState title="Rewatch history is unavailable" message={data.coverage.blockers[0] ?? 'Occurrence-level rewatch data is required for this view.'} />
        ) : echoes.length > 0 ? (
          <div>
            {visibleEchoes.map((echo) => <EchoRow key={echo.echo_id} echo={echo} />)}
            {echoes.length > 6 && (
              <div className="border-t border-white/[0.07] p-3 text-center">
                <button type="button" onClick={() => setExpanded((value) => !value)} className="btn-ghost border-white/10 px-4 py-2 text-xs">
                  {expanded ? 'Show fewer echoes' : `Show all ${echoes.length} echoes`}
                </button>
              </div>
            )}
          </div>
        ) : (
          <div className="px-5 py-10 text-center">
            <Repeat2 className="mx-auto h-7 w-7 text-white/25" />
            <p className="mt-3 text-sm font-medium text-white/65">No rewatch echoes in this window</p>
            <p className="mt-1 text-xs text-white/40">Try a wider time gap or another profile selection.</p>
          </div>
        )}
      </div>
    </section>
  );
}
