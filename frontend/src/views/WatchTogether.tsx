'use client';

import React, { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { motion } from 'framer-motion';
import { Clock3, Eye, EyeOff, Film, Globe2, Heart, ListChecks, PlayCircle, Search, Tags } from 'lucide-react';
import { useSearchParams } from 'next/navigation';

import ProfileMultiSelect from '../components/insights/ProfileMultiSelect';
import { FeatureState } from '../components/insights/InsightUI';
import WatchTogetherResults from '../components/insights/WatchTogetherResults';
import AdminScopeToggle from '../components/AdminScopeToggle';
import { useScopedProfiles } from '../hooks/useScopedProfiles';
import { useUrlProfileSelection } from '../hooks/useUrlProfileSelection';
import {
  insightsApi,
  type FeatureCoverage,
  type WatchTogetherMode,
} from '../services/api';

interface WatchFilters {
  maxRuntime?: number;
  region: string;
  availability: string;
  genre: string;
}

function parseMaxRuntime(value: string | null): number | undefined {
  if (!value) return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : undefined;
}

function parseListId(value: string | null): number | undefined {
  if (!value) return undefined;
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : undefined;
}

function sameWatchFilters(left: WatchFilters, right: WatchFilters): boolean {
  return left.maxRuntime === right.maxRuntime
    && left.region === right.region
    && left.availability === right.availability
    && left.genre === right.genre;
}

const FALLBACK_AVAILABILITY_COUNTRIES = ['DE', 'GB', 'IN', 'US'];
const WATCH_MODES: Array<{ value: WatchTogetherMode; label: string; icon: React.ComponentType<{ className?: string }> }> = [
  { value: 'unseen_pick', label: 'Unseen by all', icon: EyeOff },
  { value: 'watchlist_overlap', label: 'Watchlist overlap', icon: Eye },
  { value: 'collective_blind_spots', label: 'Collective blind spots', icon: Heart },
  { value: 'list_mission', label: 'List mission', icon: ListChecks },
];
const VALID_WATCH_MODES = new Set<WatchTogetherMode>(WATCH_MODES.map((item) => item.value));
const availabilityCountryNames = new Intl.DisplayNames(['en'], { type: 'region' });
const availabilityCountryCollator = new Intl.Collator('en');

function availabilityCountryLabel(code: string): string {
  return availabilityCountryNames.of(code) ?? code;
}

function coverageFallback(
  data: Awaited<ReturnType<typeof insightsApi.getDataCoverage>> | undefined,
): FeatureCoverage | undefined {
  const readiness = data?.feature_readiness?.find((item) => item.feature === 'watch_together');
  if (!readiness) return undefined;
  return {
    status: readiness.status,
    score: readiness.score,
    dated_watch_events: 0,
    total_watch_events: 0,
    blockers: readiness.blockers ?? [],
    warnings: readiness.warnings ?? [],
    last_updated: data?.generated_at ?? null,
  };
}

function FilterField({ icon: Icon, label, children }: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="min-w-0">
      <span className="mb-2 block text-xs font-medium text-white/45">{label}</span>
      <span className="flex min-h-11 items-center gap-2 rounded-xl border border-white/10 bg-black/20 px-3 focus-within:border-cinema-400/45">
        <Icon className="h-4 w-4 shrink-0 text-white/45" />
        {children}
      </span>
    </label>
  );
}

export default function WatchTogether() {
  const searchParams = useSearchParams();
  const requestedMode = searchParams.get('mode') as WatchTogetherMode | null;
  const mode: WatchTogetherMode = requestedMode && VALID_WATCH_MODES.has(requestedMode) ? requestedMode : 'unseen_pick';
  const appliedListId = parseListId(searchParams.get('list_id'));
  const requestedMaxRuntime = searchParams.get('max_runtime');
  const requestedRegion = searchParams.get('region');
  const requestedAvailability = searchParams.get('availability');
  const requestedGenre = searchParams.get('genre');
  const appliedFilters = useMemo<WatchFilters>(() => ({
    maxRuntime: parseMaxRuntime(requestedMaxRuntime),
    region: requestedRegion || 'ALL',
    availability: requestedAvailability || 'all',
    genre: requestedGenre || '',
  }), [requestedAvailability, requestedGenre, requestedMaxRuntime, requestedRegion]);
  const [draftListId, setDraftListId] = useState<number | undefined>(appliedListId);
  const [draftFilters, setDraftFilters] = useState<WatchFilters>(appliedFilters);

  useEffect(() => {
    setDraftListId((current) => current === appliedListId ? current : appliedListId);
  }, [appliedListId]);

  useEffect(() => {
    setDraftFilters((current) => sameWatchFilters(current, appliedFilters) ? current : appliedFilters);
  }, [appliedFilters]);

  const profilesQuery = useScopedProfiles();
  const providerRegionsQuery = useQuery({
    queryKey: ['watch-provider-regions'],
    queryFn: insightsApi.getWatchProviderRegions,
    staleTime: 24 * 60 * 60 * 1000,
  });
  const completedProfiles = useMemo(
    () => (profilesQuery.data ?? []).filter((profile) => profile.scraping_status === 'completed'),
    [profilesQuery.data],
  );
  const usernames = useMemo(() => completedProfiles.map((profile) => profile.username), [completedProfiles]);
  const selection = useUrlProfileSelection(usernames, { minSelection: 2, maxSelection: 8, defaultCount: Math.min(4, usernames.length) });
  const activeProfiles = selection.appliedProfiles;
  const canRecommend = activeProfiles.length >= 2;
  const availabilityCountries = useMemo(() => {
    const regionCodes = providerRegionsQuery.data?.regions.length
      ? providerRegionsQuery.data.regions.map((region) => region.code)
      : FALLBACK_AVAILABILITY_COUNTRIES;
    const uniqueCodes = new Set(regionCodes.map((code) => code.toUpperCase()));
    if (draftFilters.region !== 'ALL') uniqueCodes.add(draftFilters.region.toUpperCase());
    return Array.from(uniqueCodes)
      .map((code) => ({ code, label: availabilityCountryLabel(code) }))
      .sort((left, right) => availabilityCountryCollator.compare(left.label, right.label));
  }, [draftFilters.region, providerRegionsQuery.data]);

  const coverageQuery = useQuery({
    queryKey: ['data-coverage', [...activeProfiles].sort()],
    queryFn: () => insightsApi.getDataCoverage(activeProfiles),
    enabled: canRecommend,
    staleTime: 5 * 60 * 1000,
  });
  const publicListsQuery = useQuery({
    queryKey: ['public-lists', [...selection.draftProfiles].sort()],
    queryFn: () => insightsApi.getPublicLists(selection.draftProfiles),
    enabled: mode === 'list_mission' && selection.draftProfiles.length >= 2,
    staleTime: 5 * 60 * 1000,
  });
  const publicLists = useMemo(() => publicListsQuery.data?.lists ?? [], [publicListsQuery.data]);

  useEffect(() => {
    if (mode !== 'list_mission' || publicLists.length === 0) return;
    if (!draftListId || !publicLists.some((list) => list.id === draftListId)) {
      setDraftListId(publicLists[0].id);
    }
  }, [draftListId, mode, publicLists]);

  const recommendationsQuery = useQuery({
    queryKey: ['watch-together', [...activeProfiles].sort(), mode, appliedFilters, appliedListId ?? null],
    queryFn: () => insightsApi.getWatchTogether(activeProfiles, {
      mode,
      region: appliedFilters.region,
      maxRuntime: appliedFilters.maxRuntime,
      genre: appliedFilters.genre || undefined,
      availability: appliedFilters.availability,
      listId: mode === 'list_mission' ? appliedListId : undefined,
    }),
    enabled: canRecommend && (mode !== 'list_mission' || Boolean(appliedListId)),
    staleTime: 5 * 60 * 1000,
  });

  const findMovies = () => {
    if (selection.draftProfiles.length < 2) return;
    if (mode === 'list_mission' && !draftListId) return;
    selection.applyProfiles(selection.draftProfiles, {
      params: {
        mode,
        region: draftFilters.region,
        max_runtime: draftFilters.maxRuntime ? String(draftFilters.maxRuntime) : null,
        availability: draftFilters.availability,
        genre: draftFilters.genre || null,
        list_id: mode === 'list_mission' && draftListId ? String(draftListId) : null,
      },
    });
  };

  const changeMode = (nextMode: WatchTogetherMode) => {
    selection.replaceParams(activeProfiles, { mode: nextMode, list_id: nextMode === 'list_mission' && draftListId ? String(draftListId) : null });
  };

  if (profilesQuery.isLoading) return <FeatureState title="Loading profiles" message="Preparing the group picker." loading />;
  if (profilesQuery.error) return <FeatureState title="Profiles unavailable" message="The profile directory could not be loaded." />;
  if (completedProfiles.length < 2) {
    return (
      <div className="space-y-6">
        <div className="flex justify-end"><AdminScopeToggle /></div>
        <FeatureState title="Track two profiles for a group pick" message="Add or request at least two Letterboxd profiles in My Profiles before asking for a group movie pick." actionHref="/profiles" actionLabel="Open My Profiles" />
      </div>
    );
  }

  return (
    <motion.div
      className="space-y-6"
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
    >
      <header className="relative z-40 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h1 className="text-4xl font-bold text-white text-glow">Watch Together</h1>
          <p className="mt-2 text-white/60">Find the best film for this group tonight.</p>
        </div>
        <div className="flex w-full flex-col gap-3 sm:flex-row sm:items-center lg:w-auto">
          <AdminScopeToggle />
          <ProfileMultiSelect
            profiles={completedProfiles}
            selectedUsernames={selection.draftProfiles}
            minSelection={2}
            maxSelection={8}
            label="Group profiles"
            onChange={selection.setDraftProfiles}
            className="w-full lg:w-72"
          />
        </div>
      </header>

      <nav className="grid min-w-0 grid-cols-2 gap-1 rounded-xl border border-white/10 bg-black/20 p-1 sm:flex sm:overflow-x-auto" aria-label="Watch Together mode">
        {WATCH_MODES.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.value}
              type="button"
              aria-pressed={mode === item.value}
              onClick={() => changeMode(item.value)}
              className={`flex min-w-0 flex-1 items-center justify-center gap-2 rounded-lg px-2 py-2.5 text-xs font-semibold transition-colors sm:min-w-max sm:px-3 ${mode === item.value ? 'bg-cinema-500/15 text-cinema-300 ring-1 ring-cinema-400/40' : 'text-white/45 hover:bg-white/[0.04] hover:text-white'}`}
            >
              <Icon className="h-4 w-4" /> {item.label}
            </button>
          );
        })}
      </nav>

      <section className="relative z-20 grid gap-3 panel-insight p-3 sm:grid-cols-2 xl:grid-cols-[.8fr_.9fr_1fr_.9fr_auto] xl:items-end">
        <FilterField icon={Clock3} label="Runtime">
          <select
            value={draftFilters.maxRuntime ?? ''}
            onChange={(event) => setDraftFilters((current) => ({ ...current, maxRuntime: event.target.value ? Number(event.target.value) : undefined }))}
            className="w-full cursor-pointer bg-transparent text-sm font-medium text-white/80 outline-none"
          >
            <option value="" className="bg-noir-900">Any</option>
            <option value="90" className="bg-noir-900">Up to 90 min</option>
            <option value="120" className="bg-noir-900">Up to 120 min</option>
            <option value="150" className="bg-noir-900">Up to 150 min</option>
            <option value="180" className="bg-noir-900">Up to 180 min</option>
          </select>
        </FilterField>
        <FilterField icon={Globe2} label="Availability country">
          <select value={draftFilters.region} onChange={(event) => setDraftFilters((current) => ({ ...current, region: event.target.value }))} className="w-full cursor-pointer bg-transparent text-sm font-medium text-white/80 outline-none">
            <option value="ALL" className="bg-noir-900">Worldwide (any country)</option>
            {availabilityCountries.map((country) => (
              <option key={country.code} value={country.code} className="bg-noir-900">
                {country.label}
              </option>
            ))}
          </select>
        </FilterField>
        <FilterField icon={PlayCircle} label="Availability">
          <select value={draftFilters.availability} onChange={(event) => setDraftFilters((current) => ({ ...current, availability: event.target.value }))} className="w-full cursor-pointer bg-transparent text-sm font-medium text-white/80 outline-none">
            <option value="streaming" className="bg-noir-900">Streaming</option>
            <option value="rent" className="bg-noir-900">Rent</option>
            <option value="buy" className="bg-noir-900">Buy</option>
            <option value="all" className="bg-noir-900">Any availability</option>
          </select>
        </FilterField>
        <FilterField icon={Tags} label="Genre">
          <select value={draftFilters.genre} onChange={(event) => setDraftFilters((current) => ({ ...current, genre: event.target.value }))} className="w-full cursor-pointer bg-transparent text-sm font-medium text-white/80 outline-none">
            <option value="" className="bg-noir-900">Any</option>
            {['Action', 'Animation', 'Comedy', 'Drama', 'Horror', 'Romance', 'Science Fiction', 'Thriller'].map((genre) => <option key={genre} value={genre} className="bg-noir-900">{genre}</option>)}
          </select>
        </FilterField>
        <button type="button" onClick={findMovies} disabled={selection.draftProfiles.length < 2 || (mode === 'list_mission' && !draftListId) || recommendationsQuery.isFetching} className="btn-primary flex min-h-11 items-center justify-center gap-2 px-5 py-2.5 text-sm sm:col-span-2 xl:col-span-1">
          <Search className="h-4 w-4" /> {recommendationsQuery.isFetching ? 'Finding…' : 'Find Movies'}
        </button>
      </section>

      {mode === 'list_mission' && (
        <section className="panel-insight p-3">
          <label className="grid gap-2 lg:grid-cols-[14rem_minmax(0,1fr)] lg:items-center">
            <span>
              <span className="flex items-center gap-2 text-sm font-semibold text-white"><ListChecks className="h-4 w-4 text-cinema-400" /> Public list mission</span>
              <span className="mt-1 block text-xs text-white/40">Rank unseen entries from one imported public list.</span>
            </span>
            <select
              value={draftListId ?? ''}
              onChange={(event) => setDraftListId(event.target.value ? Number(event.target.value) : undefined)}
              disabled={publicListsQuery.isLoading || publicLists.length === 0}
              className="min-h-11 w-full cursor-pointer rounded-xl border border-white/10 bg-noir-900 px-3 text-sm font-medium text-white/80 outline-none focus:border-cinema-400/45 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {publicListsQuery.isLoading ? <option value="">Loading public lists…</option> : publicLists.length === 0 ? <option value="">No imported public lists for this group</option> : publicLists.map((list) => (
                <option key={list.id} value={list.id}>{list.owner} · {list.name} ({list.movie_count.toLocaleString()} films)</option>
              ))}
            </select>
          </label>
          {publicListsQuery.error && <p className="mt-2 text-xs text-red-300">Public lists could not be loaded. Existing Watch Together modes are still available.</p>}
        </section>
      )}

      {mode === 'list_mission' && !appliedListId ? (
        <FeatureState title="Choose a public list" message="Select a list mission above, then find movies to rank its unseen entries for this group." />
      ) : recommendationsQuery.isLoading ? (
        <FeatureState title="Ranking group picks" message="Combining watchlists, ratings, unseen status, metadata, and availability." loading />
      ) : (
        <WatchTogetherResults
          data={recommendationsQuery.data}
          coverage={coverageFallback(coverageQuery.data)}
        />
      )}

      <footer className="space-y-3 border-t border-white/10 py-3 text-[11px] text-white/35">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
          <span className="flex items-center gap-1.5"><Film className="h-3.5 w-3.5" /> Rankings use only imported profile data.</span>
          <span>Availability country controls where streaming, rental, and purchase offers are checked. Worldwide means any supported country.</span>
        </div>
        <section aria-labelledby="watch-data-credits" className="flex flex-col gap-2 rounded-lg border border-white/[0.07] bg-black/10 px-3 py-2 sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-4">
          <h2 id="watch-data-credits" className="text-[11px] font-semibold uppercase tracking-wide text-white/50">Data credits</h2>
          <a
            href="https://www.justwatch.com/"
            target="_blank"
            rel="noreferrer"
            className="underline decoration-white/20 underline-offset-2 hover:text-white/60"
          >
            Streaming availability data powered by JustWatch
          </a>
          <span className="flex flex-wrap items-center gap-2">
            <a href="https://www.themoviedb.org/" target="_blank" rel="noreferrer" aria-label="The Movie Database">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src="https://www.themoviedb.org/assets/2/v4/logos/v2/blue_short-8e7b30f73a4020692ccca9c88bafe5dcb6f8a62a4c6bc55cd9ba82bb2cd95f6c.svg"
                alt="TMDB"
                className="h-3.5 w-auto opacity-75"
              />
            </a>
            <span>This product uses the TMDB API but is not endorsed or certified by TMDB.</span>
          </span>
        </section>
      </footer>
    </motion.div>
  );
}
