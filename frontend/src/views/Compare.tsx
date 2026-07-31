'use client';

import React, { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { motion } from 'framer-motion';
import { ArrowLeftRight, BarChart3, CalendarDays, Dna, Scale, TrendingUp } from 'lucide-react';
import { useSearchParams } from 'next/navigation';

import {
  PairDossierPanel,
  SignalCalendarPanel,
  TasteDnaPanel,
} from '../components/insights/ComparePanels';
import TasteTimelinePanel from '../components/insights/TasteTimelinePanel';
import { FeatureState, ProfileAvatar, WorkspaceTabs } from '../components/insights/InsightUI';
import AdminScopeToggle from '../components/AdminScopeToggle';
import { useScopedProfiles } from '../hooks/useScopedProfiles';
import { useUrlProfileSelection } from '../hooks/useUrlProfileSelection';
import {
  insightsApi,
  profileApi,
  type DataCoverageResponse,
  type FeatureCoverage,
  type FeatureReadinessStatus,
} from '../services/api';

type CompareTab = 'pair' | 'taste' | 'timeline' | 'calendar';

const TAB_ITEMS: Array<{ id: CompareTab; label: string }> = [
  { id: 'pair', label: 'Pair Dossier' },
  { id: 'taste', label: 'Taste DNA' },
  { id: 'timeline', label: 'Taste Through Time' },
  { id: 'calendar', label: 'Signal Calendar' },
];

const VALID_WINDOWS = new Set([1, 7, 30]);

function featureCoverageFromResponse(
  response: DataCoverageResponse | undefined,
  feature: 'pair_dossier' | 'taste_dna' | 'taste_timeline' | 'signal_calendar',
): FeatureCoverage | undefined {
  const readiness = response?.feature_readiness?.find((item) => item.feature === feature);
  if (!readiness) return undefined;
  return {
    status: readiness.status,
    score: readiness.score,
    dated_watch_events: 0,
    total_watch_events: 0,
    blockers: readiness.blockers ?? [],
    warnings: readiness.warnings ?? [],
    last_updated: response?.generated_at ?? null,
  };
}

function getDateRange(): { from: string; to: string } {
  const now = new Date();
  const to = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
  const from = new Date(to.getTime() - 364 * 86_400_000);
  return { from: from.toISOString().slice(0, 10), to: to.toISOString().slice(0, 10) };
}

function PairProfileField({
  label,
  value,
  profiles,
  excludedUsername,
  onChange,
}: {
  label: string;
  value: string;
  profiles: Awaited<ReturnType<typeof profileApi.getProfiles>>;
  excludedUsername: string;
  onChange: (value: string) => void;
}) {
  const selected = profiles.find((profile) => profile.username === value);
  return (
    <label className="block min-w-0 rounded-xl border border-white/15 bg-white/[0.025] px-4 py-3 transition-colors focus-within:border-cinema-400/45">
      <span className="block text-xs font-medium text-white/45">{label}</span>
      <span className="mt-2 flex items-center gap-3">
        <ProfileAvatar profile={selected} size="lg" />
        <span className="min-w-0 flex-1">
          <select
            value={value}
            onChange={(event) => onChange(event.target.value)}
            className="w-full cursor-pointer appearance-none bg-transparent text-sm font-semibold text-white outline-none"
          >
            {profiles.map((profile) => (
              <option key={profile.username} value={profile.username} disabled={profile.username === excludedUsername} className="bg-noir-900 text-white">
                {profile.username}
              </option>
            ))}
          </select>
          <span className="mt-1 block text-xs text-white/40">{selected?.total_films.toLocaleString() ?? 0} films</span>
        </span>
      </span>
    </label>
  );
}

export default function Compare() {
  const searchParams = useSearchParams();
  const requestedTab = searchParams.get('tab') as CompareTab | null;
  const activeTab: CompareTab = requestedTab && TAB_ITEMS.some((item) => item.id === requestedTab) ? requestedTab : 'pair';
  const requestedWindow = Number(searchParams.get('window') ?? 7);
  const windowDays = VALID_WINDOWS.has(requestedWindow) ? requestedWindow : 7;

  const profilesQuery = useScopedProfiles();
  const completedProfiles = useMemo(
    () => (profilesQuery.data ?? []).filter((profile) => profile.scraping_status === 'completed'),
    [profilesQuery.data],
  );
  const usernames = useMemo(() => completedProfiles.map((profile) => profile.username), [completedProfiles]);
  const selection = useUrlProfileSelection(usernames, { minSelection: 2, maxSelection: 2, defaultCount: 2 });

  const activeProfiles = selection.appliedProfiles;
  const canCompare = activeProfiles.length === 2;
  const coverageQuery = useQuery({
    queryKey: ['data-coverage', [...activeProfiles].sort()],
    queryFn: () => insightsApi.getDataCoverage(activeProfiles),
    enabled: canCompare,
    staleTime: 5 * 60 * 1000,
  });
  const pairQuery = useQuery({
    queryKey: ['pair-dossier', activeProfiles, windowDays],
    queryFn: () => insightsApi.getPairDossier(activeProfiles, windowDays),
    enabled: canCompare && activeTab === 'pair',
    staleTime: 2 * 60 * 1000,
  });
  const tasteQuery = useQuery({
    queryKey: ['taste-dna', activeProfiles],
    queryFn: () => insightsApi.getTasteDna(activeProfiles),
    enabled: canCompare && activeTab === 'taste',
    staleTime: 10 * 60 * 1000,
  });
  const tasteTimelineQuery = useQuery({
    queryKey: ['taste-timeline', activeProfiles],
    queryFn: () => insightsApi.getTasteTimeline(activeProfiles),
    enabled: canCompare && activeTab === 'timeline',
    staleTime: 10 * 60 * 1000,
  });
  const dateRange = useMemo(() => getDateRange(), []);
  const calendarQuery = useQuery({
    queryKey: ['signal-calendar', activeProfiles, windowDays, dateRange.from, dateRange.to],
    queryFn: () => insightsApi.getSignalCalendar(activeProfiles, { gapDays: windowDays, ...dateRange }),
    enabled: canCompare && activeTab === 'calendar',
    staleTime: 5 * 60 * 1000,
  });

  const updateDraftProfile = (index: 0 | 1, username: string) => {
    selection.setDraftProfiles((current) => {
      const next = current.length >= 2 ? [...current] : usernames.slice(0, 2);
      next[index] = username;
      if (next[0] === next[1]) {
        const replacement = usernames.find((value) => value !== username);
        if (replacement) next[index === 0 ? 1 : 0] = replacement;
      }
      return next;
    });
  };

  const applyComparison = () => {
    selection.applyProfiles(selection.draftProfiles, {
      params: { tab: activeTab, window: String(windowDays) },
    });
  };

  const changeTab = (tab: CompareTab) => {
    selection.replaceParams(activeProfiles, { tab, window: String(windowDays) });
  };

  const changeWindow = (value: number) => {
    selection.replaceParams(activeProfiles, { tab: activeTab, window: String(value) });
  };

  const activeFeature = activeTab === 'pair'
    ? 'pair_dossier'
    : activeTab === 'taste'
      ? 'taste_dna'
      : activeTab === 'timeline'
        ? 'taste_timeline'
        : 'signal_calendar';
  const fallbackCoverage = featureCoverageFromResponse(coverageQuery.data, activeFeature);
  const activeLoading = activeTab === 'pair'
    ? pairQuery.isLoading
    : activeTab === 'taste'
      ? tasteQuery.isLoading
      : activeTab === 'timeline'
        ? tasteTimelineQuery.isLoading
        : calendarQuery.isLoading;

  if (profilesQuery.isLoading) return <FeatureState title="Loading profiles" message="Preparing the comparison workspace." loading />;
  if (profilesQuery.error) return <FeatureState title="Profiles unavailable" message="The profile directory could not be loaded." />;
  if (completedProfiles.length < 2) {
    return (
      <div className="mx-auto max-w-[92rem] space-y-5">
        <div className="flex justify-end"><AdminScopeToggle /></div>
        <FeatureState title="Track two profiles to compare" message="Add or request at least two Letterboxd profiles in My Profiles before opening Compare." actionHref="/profiles" actionLabel="Open My Profiles" />
      </div>
    );
  }

  return (
    <motion.div
      className="mx-auto max-w-[92rem] space-y-5"
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
    >
      <header className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">Compare Profiles</h1>
          <p className="mt-2 text-sm text-white/55">Understand how two people&apos;s movie lives overlap.</p>
        </div>
        <div className="flex flex-wrap items-center gap-3 self-start">
        <AdminScopeToggle />
        <div className="flex items-center gap-1 rounded-xl border border-white/12 bg-black/15 p-1" aria-label="Comparison time window">
          {[1, 7, 30].map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={windowDays === value}
              onClick={() => changeWindow(value)}
              className={`rounded-lg px-3 py-2 text-xs font-semibold transition-colors ${windowDays === value ? 'bg-cinema-500 text-white shadow-glow' : 'text-white/50 hover:bg-white/5 hover:text-white'}`}
            >
              {value === 1 ? '1 day' : `${value} days`}
            </button>
          ))}
        </div>
        </div>
      </header>

      <section className="relative z-20 grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)_auto] lg:items-center">
        <PairProfileField
          label="Profile A"
          value={selection.draftProfiles[0] ?? usernames[0]}
          profiles={completedProfiles}
          excludedUsername={selection.draftProfiles[1] ?? ''}
          onChange={(value) => updateDraftProfile(0, value)}
        />
        <button
          type="button"
          onClick={() => selection.setDraftProfiles(([left, right]) => [right, left].filter(Boolean))}
          className="btn-ghost flex items-center justify-center gap-2 border-white/10 px-4 py-3 text-xs lg:self-center"
        >
          <ArrowLeftRight className="h-4 w-4" /> Swap
        </button>
        <PairProfileField
          label="Profile B"
          value={selection.draftProfiles[1] ?? usernames[1]}
          profiles={completedProfiles}
          excludedUsername={selection.draftProfiles[0] ?? ''}
          onChange={(value) => updateDraftProfile(1, value)}
        />
        <button type="button" onClick={applyComparison} className="btn-primary flex min-h-12 items-center justify-center gap-2 px-6 py-3 text-sm">
          <BarChart3 className="h-4 w-4" /> Compare
        </button>
      </section>

      <WorkspaceTabs activeTab={activeTab} items={TAB_ITEMS} onChange={changeTab} />

      <section role="tabpanel" aria-label={TAB_ITEMS.find((item) => item.id === activeTab)?.label}>
        {activeLoading ? (
          <FeatureState title={`Loading ${TAB_ITEMS.find((item) => item.id === activeTab)?.label}`} message="Calculating this comparison from the imported histories." loading />
        ) : activeTab === 'pair' ? (
          <PairDossierPanel data={pairQuery.data} coverage={fallbackCoverage} />
        ) : activeTab === 'taste' ? (
          <TasteDnaPanel data={tasteQuery.data} coverage={fallbackCoverage} profiles={activeProfiles} />
        ) : activeTab === 'timeline' ? (
          <TasteTimelinePanel data={tasteTimelineQuery.data} coverage={fallbackCoverage} />
        ) : (
          <SignalCalendarPanel data={calendarQuery.data} coverage={fallbackCoverage} />
        )}
      </section>

      <footer className="flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-white/10 py-3 text-[11px] text-white/35">
        <span className="flex items-center gap-1.5"><Scale className="h-3.5 w-3.5" /> Pair Dossier uses behavior and ratings.</span>
        <span className="flex items-center gap-1.5"><Dna className="h-3.5 w-3.5" /> Taste DNA depends on TMDB metadata.</span>
        <span className="flex items-center gap-1.5"><TrendingUp className="h-3.5 w-3.5" /> Taste Through Time uses dated events only.</span>
        <span className="flex items-center gap-1.5"><CalendarDays className="h-3.5 w-3.5" /> Calendar signals require dated watch events.</span>
      </footer>
    </motion.div>
  );
}
