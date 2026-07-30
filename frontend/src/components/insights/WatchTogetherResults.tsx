'use client';

import React, { useEffect, useMemo, useState } from 'react';
import {
  ExternalLink,
  EyeOff,
  Heart,
  Info,
  PlayCircle,
  Sparkles,
  Tags,
  Users,
  X,
} from 'lucide-react';

import type {
  FeatureCoverage,
  WatchTogetherCandidate,
  WatchTogetherResponse,
} from '../../services/api';
import { CoverageBanner, FeatureState, MoviePoster, ScoreRing } from './InsightUI';

type ResultSort = 'group_fit' | 'watchlists' | 'runtime';

function providerSummary(candidate: WatchTogetherCandidate): string {
  const regionCounts = new Map<string, number>();
  for (const provider of candidate.movie.providers ?? []) {
    regionCounts.set(
      provider.name,
      Math.max(regionCounts.get(provider.name) ?? 0, provider.regions?.length ?? 0),
    );
  }
  const labels = Array.from(regionCounts, ([name, regionCount]) => (
    regionCount > 1 ? `${name} (${regionCount} countries)` : name
  ));
  return labels.length > 0 ? labels.slice(0, 2).join(' · ') : 'Availability unknown';
}

function letterboxdFilmUrl(slug: string | null): string | null {
  const normalizedSlug = slug?.trim().replace(/^\/+|\/+$/g, '');
  return normalizedSlug ? `https://letterboxd.com/film/${encodeURIComponent(normalizedSlug)}/` : null;
}

function CandidateRow({
  candidate,
  index,
  selected,
  selectedProfileCount,
  onSelect,
}: {
  candidate: WatchTogetherCandidate;
  index: number;
  selected: boolean;
  selectedProfileCount: number;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={`grid w-full grid-cols-[2rem_minmax(11rem,2fr)_5rem_5rem_5rem_minmax(8rem,1fr)_minmax(9rem,1fr)_minmax(10rem,1.3fr)] items-center gap-3 border-t px-3 py-3 text-left transition-colors first:border-t-0 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-cinema-400/70 ${
        selected ? 'border-cinema-400/70 bg-cinema-500/[0.08] shadow-[inset_3px_0_0_#f57c00]' : 'border-white/[0.07] hover:bg-white/[0.035]'
      }`}
    >
      <span className={`text-center text-sm font-bold ${selected ? 'text-cinema-300' : 'text-white/55'}`}>{index + 1}</span>
      <span className="flex min-w-0 items-center gap-3">
        <MoviePoster movie={candidate.movie} className="h-16 w-11" />
        <span className="min-w-0">
          <span className="block truncate text-sm font-semibold text-white/85">{candidate.movie.title}</span>
          <span className="mt-1 block text-xs text-white/40">
            {candidate.movie.year ?? 'Year unknown'}
            {candidate.movie.runtime_minutes ? ` · ${candidate.movie.runtime_minutes}m` : ''}
          </span>
        </span>
      </span>
      <ScoreRing score={candidate.group_fit_score} size="sm" />
      <span className="text-center">
        <span className="block text-sm font-semibold text-white/80">{candidate.on_watchlist_by.length} / {selectedProfileCount}</span>
        <span className="text-[10px] text-white/35">want it</span>
      </span>
      <span className="text-center">
        <span className="block text-sm font-semibold text-white/80">{candidate.watched_by.length} / {selectedProfileCount}</span>
        <span className="text-[10px] text-white/35">seen it</span>
      </span>
      <span className="line-clamp-2 text-xs leading-5 text-white/50">{candidate.movie.genres?.join(', ') || 'Genres unavailable'}</span>
      <span className="line-clamp-2 text-xs leading-5 text-white/55">{providerSummary(candidate)}</span>
      <span className="line-clamp-2 text-xs leading-5 text-white/50">{candidate.reasons?.[0] ?? 'Ranked from the available group signals.'}</span>
    </button>
  );
}

function CandidateCard({
  candidate,
  index,
  selected,
  selectedProfileCount,
  onSelect,
}: {
  candidate: WatchTogetherCandidate;
  index: number;
  selected: boolean;
  selectedProfileCount: number;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={`grid w-full grid-cols-[2rem_3.25rem_minmax(0,1fr)_3.5rem] items-center gap-3 border-t px-3 py-3 text-left first:border-t-0 ${selected ? 'border-cinema-400/70 bg-cinema-500/[0.08]' : 'border-white/[0.07]'}`}
    >
      <span className={`text-center text-sm font-bold ${selected ? 'text-cinema-300' : 'text-white/50'}`}>{index + 1}</span>
      <MoviePoster movie={candidate.movie} className="h-[4.5rem] w-12" />
      <span className="min-w-0">
        <span className="block truncate text-sm font-semibold text-white/85">{candidate.movie.title}</span>
        <span className="mt-1 block text-[11px] text-white/40">{candidate.movie.year ?? '—'}{candidate.movie.runtime_minutes ? ` · ${candidate.movie.runtime_minutes}m` : ''}</span>
        <span className="mt-1 line-clamp-1 block text-[11px] text-white/45">{candidate.movie.genres?.join(', ') || providerSummary(candidate)}</span>
        <span className="mt-1 block text-[11px] text-white/50">{candidate.on_watchlist_by.length}/{selectedProfileCount} want · {candidate.watched_by.length}/{selectedProfileCount} seen</span>
      </span>
      <ScoreRing score={candidate.group_fit_score} size="sm" />
    </button>
  );
}

function WhyPanel({ candidate, onClose }: {
  candidate: WatchTogetherCandidate;
  onClose: () => void;
}) {
  const tmdbUrl = candidate.movie.tmdb_id ? `https://www.themoviedb.org/movie/${candidate.movie.tmdb_id}` : null;
  const letterboxdUrl = letterboxdFilmUrl(candidate.movie.letterboxd_slug);
  return (
    <aside className="rounded-xl border border-cinema-400/25 bg-[#0a1626] p-5 shadow-2xl shadow-black/30 2xl:sticky 2xl:top-5">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-white">Why this ranked first</h2>
        <button type="button" onClick={onClose} className="grid h-8 w-8 place-items-center rounded-lg text-white/45 hover:bg-white/5 hover:text-white" aria-label="Close explanation">
          <X className="h-5 w-5" />
        </button>
      </div>

      <div className="mt-5 flex gap-4 border-b border-white/10 pb-5">
        <MoviePoster movie={candidate.movie} className="h-36 w-24" />
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-base font-semibold text-white/90">{candidate.movie.title}</h3>
          <p className="mt-1 text-sm text-white/45">{candidate.movie.year ?? '—'}{candidate.movie.runtime_minutes ? ` · ${candidate.movie.runtime_minutes}m` : ''}</p>
          <p className="mt-2 line-clamp-2 text-xs leading-5 text-white/45">{candidate.movie.genres?.join(', ') || 'Metadata unavailable'}</p>
          <div className="mt-4 flex items-center gap-3">
            <ScoreRing score={candidate.group_fit_score} size="md" />
            <div>
              <p className="text-sm font-semibold text-white">{candidate.group_fit_score >= 85 ? 'Excellent' : candidate.group_fit_score >= 70 ? 'Strong' : 'Possible'} group fit</p>
              <p className="mt-1 text-xs text-white/40">Based on the available factors</p>
            </div>
          </div>
        </div>
      </div>

      <div className="py-5">
        <h3 className="text-sm font-semibold text-white">What&apos;s driving this</h3>
        <div className="mt-4 space-y-4">
          {(candidate.reasons ?? []).slice(0, 6).map((reason, index) => {
            const Icon = index === 0 ? Users : index === 1 ? Sparkles : index === 2 ? EyeOff : index === 3 ? Tags : PlayCircle;
            return (
              <div key={`${reason}-${index}`} className="flex gap-3">
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-cinema-400/25 bg-cinema-500/[0.07] text-cinema-400">
                  <Icon className="h-4 w-4" />
                </span>
                <p className="text-sm leading-6 text-white/60">{reason}</p>
              </div>
            );
          })}
          {(candidate.reasons ?? []).length === 0 && <p className="text-sm text-white/40">No detailed ranking explanation was returned.</p>}
        </div>
      </div>

      <div className="space-y-3 border-t border-white/10 py-5 text-sm">
        <h3 className="font-semibold text-white">Group signals</h3>
        <div className="flex items-center justify-between gap-4 text-white/50"><span>Appears on watchlists</span><strong className="text-white/80">{candidate.on_watchlist_by.length}</strong></div>
        <div className="flex items-center justify-between gap-4 text-white/50"><span>Already watched</span><strong className="text-white/80">{candidate.watched_by.length}</strong></div>
        <div className="flex items-center justify-between gap-4 text-white/50"><span>Liked by</span><strong className="text-white/80">{candidate.liked_by.length}</strong></div>
        <div className="flex items-center justify-between gap-4 text-white/50"><span>Where to watch</span><strong className="max-w-40 truncate text-white/80">{providerSummary(candidate)}</strong></div>
      </div>

      {candidate.blind_spot_source && (
        <div className="mb-5 rounded-lg border border-cinema-400/20 bg-cinema-500/[0.06] px-3 py-3 text-xs leading-5 text-white/55">
          <strong className="text-white/80">Blind-spot source:</strong> {candidate.blind_spot_source.username}
          {candidate.blind_spot_source.rating !== null ? ` rated it ${candidate.blind_spot_source.rating.toFixed(1)}` : ' watched it'}
          {candidate.blind_spot_source.liked ? ' and liked it' : ''}; everyone else selected has no observed watch.
        </div>
      )}

      {candidate.list_context && (
        <div className="mb-5 rounded-lg border border-white/10 bg-white/[0.025] px-3 py-3 text-xs leading-5 text-white/55">
          <strong className="text-white/80">List mission:</strong> {candidate.list_context.owner} · {candidate.list_context.name}
          {candidate.list_context.position ? ` · #${candidate.list_context.position}` : ''}
          {candidate.list_context.notes ? <span className="mt-1 block text-white/40">{candidate.list_context.notes}</span> : null}
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        {letterboxdUrl ? (
          <a href={letterboxdUrl} target="_blank" rel="noreferrer" className="btn-secondary flex w-full items-center justify-center gap-2 px-4 py-2.5 text-sm">
            View film on Letterboxd <ExternalLink className="h-4 w-4" />
          </a>
        ) : (
          <p className="rounded-lg border border-white/10 bg-white/[0.025] px-3 py-2 text-center text-xs text-white/40">Letterboxd link unavailable</p>
        )}
        {tmdbUrl ? (
          <a href={tmdbUrl} target="_blank" rel="noreferrer" className="btn-secondary flex w-full items-center justify-center gap-2 px-4 py-2.5 text-sm">
            View film on TMDB <ExternalLink className="h-4 w-4" />
          </a>
        ) : (
          <p className="rounded-lg border border-white/10 bg-white/[0.025] px-3 py-2 text-center text-xs text-white/40">TMDB link unavailable</p>
        )}
      </div>
    </aside>
  );
}

export default function WatchTogetherResults({
  data,
  coverage,
}: {
  data?: WatchTogetherResponse;
  coverage?: FeatureCoverage;
}) {
  const [sort, setSort] = useState<ResultSort>('group_fit');
  const [selectedMovieKey, setSelectedMovieKey] = useState<string | null>(null);
  const effectiveCoverage = data?.coverage ?? coverage;
  const recommendations = useMemo(() => {
    const rows = [...(data?.recommendations ?? [])];
    if (sort === 'watchlists') return rows.sort((left, right) => right.on_watchlist_by.length - left.on_watchlist_by.length);
    if (sort === 'runtime') return rows.sort((left, right) => (left.movie.runtime_minutes ?? Number.MAX_SAFE_INTEGER) - (right.movie.runtime_minutes ?? Number.MAX_SAFE_INTEGER));
    return rows.sort((left, right) => right.group_fit_score - left.group_fit_score);
  }, [data?.recommendations, sort]);

  useEffect(() => {
    const first = recommendations[0];
    if (!first) {
      setSelectedMovieKey(null);
      return;
    }
    const firstKey = `${first.movie.movie_id ?? first.movie.title}-${first.movie.year ?? ''}`;
    setSelectedMovieKey((current) => current && recommendations.some((candidate) => `${candidate.movie.movie_id ?? candidate.movie.title}-${candidate.movie.year ?? ''}` === current) ? current : firstKey);
  }, [recommendations]);

  if (!data) {
    return (
      <div className="space-y-4">
        {effectiveCoverage && <CoverageBanner coverage={effectiveCoverage} />}
        <FeatureState
          title={effectiveCoverage?.status === 'blocked' ? 'Watch Together needs watchlist data' : 'Recommendations are unavailable'}
          message={effectiveCoverage?.blockers?.[0] ?? 'The recommendation service did not return group candidates.'}
        />
      </div>
    );
  }

  if (data.coverage.status === 'blocked') {
    return (
      <div className="space-y-4">
        <CoverageBanner coverage={data.coverage} />
        <FeatureState title="Watch Together is blocked" message={data.coverage.blockers[0] ?? 'Sync watchlists or TMDB metadata before generating group picks.'} />
      </div>
    );
  }

  const selectedCandidate = recommendations.find((candidate) => `${candidate.movie.movie_id ?? candidate.movie.title}-${candidate.movie.year ?? ''}` === selectedMovieKey) ?? null;
  const blindSpots = recommendations.filter((candidate) => candidate.watched_by.length === 0).slice(0, 8);
  const modeLabel = data.mode === 'collective_blind_spots'
    ? 'Collective blind spots'
    : data.mode === 'list_mission'
      ? 'List mission'
      : data.mode === 'watchlist_overlap'
        ? 'Watchlist overlap'
        : 'Unseen by all';

  return (
    <div className="space-y-4">
      <CoverageBanner coverage={data.coverage} />
      <div className={`grid min-w-0 grid-cols-[minmax(0,1fr)] gap-4 ${selectedCandidate ? '2xl:grid-cols-[minmax(0,1fr)_20rem]' : ''}`}>
        <div className="min-w-0 space-y-4">
          <section className="overflow-hidden rounded-xl border border-white/12 bg-white/[0.02]">
            <div className="flex flex-col gap-3 border-b border-white/10 px-3 py-2.5 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="text-xs font-semibold text-white/75">{modeLabel}</p>
                <p className="mt-0.5 text-[11px] text-white/35">
                  {data.selected_list ? `${data.selected_list.owner} · ${data.selected_list.name}` : `${data.summary.candidates} ranked candidates`}
                </p>
              </div>
              <label className="flex items-center gap-2 text-xs text-white/45">
                Sort by
                <select value={sort} onChange={(event) => setSort(event.target.value as ResultSort)} className="rounded-lg border border-white/12 bg-noir-900 px-3 py-2 text-xs font-medium text-white outline-none focus:border-cinema-400/45">
                  <option value="group_fit">Best group fit</option>
                  <option value="watchlists">Most watchlists</option>
                  <option value="runtime">Shortest runtime</option>
                </select>
              </label>
            </div>

            {recommendations.length > 0 ? (
              <>
                <div className="hidden grid-cols-[2rem_minmax(11rem,2fr)_5rem_5rem_5rem_minmax(8rem,1fr)_minmax(9rem,1fr)_minmax(10rem,1.3fr)] gap-3 border-b border-white/10 px-3 py-2 text-[10px] font-medium uppercase tracking-wide text-white/35 lg:grid">
                  <span>#</span><span>Title</span><span>Group fit</span><span>Want it</span><span>Seen it</span><span>Genres</span><span>Where to watch</span><span>Why it fits</span>
                </div>
                <div className="hidden lg:block">
                  {recommendations.slice(0, 20).map((candidate, index) => {
                    const key = `${candidate.movie.movie_id ?? candidate.movie.title}-${candidate.movie.year ?? ''}`;
                    return <CandidateRow key={key} candidate={candidate} index={index} selected={key === selectedMovieKey} selectedProfileCount={data.selected_profiles.length} onSelect={() => setSelectedMovieKey(key)} />;
                  })}
                </div>
                <div className="lg:hidden">
                  {recommendations.slice(0, 20).map((candidate, index) => {
                    const key = `${candidate.movie.movie_id ?? candidate.movie.title}-${candidate.movie.year ?? ''}`;
                    return <CandidateCard key={key} candidate={candidate} index={index} selected={key === selectedMovieKey} selectedProfileCount={data.selected_profiles.length} onSelect={() => setSelectedMovieKey(key)} />;
                  })}
                </div>
              </>
            ) : (
              <div className="px-6 py-16 text-center">
                <Info className="mx-auto h-8 w-8 text-cinema-400" />
                <h2 className="mt-4 text-lg font-semibold text-white">No group picks match these filters</h2>
                <p className="mt-2 text-sm text-white/45">Try a longer runtime, another region, or watchlist overlap mode.</p>
              </div>
            )}
          </section>

          {blindSpots.length > 0 && (
            <section className="rounded-xl border border-white/12 bg-white/[0.02] p-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <h2 className="flex items-center gap-2 text-sm font-semibold text-white"><Heart className="h-4 w-4 text-cinema-400" /> Mutual blind spots</h2>
                  <p className="mt-1 text-xs text-white/40">Highly ranked films that nobody in the group has watched.</p>
                </div>
                <span className="text-xs font-semibold text-cinema-300">{data.summary.unseen_by_everyone} candidates</span>
              </div>
              <div className="mt-4 flex gap-3 overflow-x-auto pb-2">
                {blindSpots.map((candidate) => (
                  <button
                    key={`${candidate.movie.movie_id ?? candidate.movie.title}-blind`}
                    type="button"
                    onClick={() => setSelectedMovieKey(`${candidate.movie.movie_id ?? candidate.movie.title}-${candidate.movie.year ?? ''}`)}
                    className="flex w-44 shrink-0 items-center gap-3 rounded-lg border border-white/10 bg-white/[0.025] p-2 text-left hover:border-cinema-400/25"
                  >
                    <MoviePoster movie={candidate.movie} className="h-16 w-11" />
                    <span className="min-w-0">
                      <span className="line-clamp-2 text-xs font-semibold text-white/75">{candidate.movie.title}</span>
                      <span className="mt-1 block text-[10px] text-white/35">Fit {Math.round(candidate.group_fit_score)}</span>
                    </span>
                  </button>
                ))}
              </div>
            </section>
          )}
        </div>
        {selectedCandidate && <WhyPanel candidate={selectedCandidate} onClose={() => setSelectedMovieKey(null)} />}
      </div>
    </div>
  );
}
