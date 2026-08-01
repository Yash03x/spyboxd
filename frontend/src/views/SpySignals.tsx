'use client';

import React, { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { motion } from 'framer-motion';
import { AlertTriangle, Radar } from 'lucide-react';

import ErrorMessage from '../components/ErrorMessage';
import LoadingSpinner from '../components/LoadingSpinner';
import SpySignalsControls, { type SignalGapDays } from '../components/SpySignalsControls';
import SpySignalsResults from '../components/SpySignalsResults';
import RewatchEchoesPanel from '../components/insights/RewatchEchoesPanel';
import AdminScopeToggle from '../components/AdminScopeToggle';
import { useAdminScope } from '../hooks/useAdminScope';
import { useScopedProfiles } from '../hooks/useScopedProfiles';
import { spySignalsApi } from '../services/api';

const VALID_GAPS = new Set<SignalGapDays>([0, 1, 3]);

function readQueryState(params: URLSearchParams): { profiles: string[]; gapDays: SignalGapDays } {
  const repeatedProfiles = params.getAll('profiles');
  const profiles = repeatedProfiles.length === 1 && repeatedProfiles[0].includes(',')
    ? repeatedProfiles[0].split(',').map((profile) => profile.trim()).filter(Boolean)
    : repeatedProfiles;
  const rawGap = params.get('gap_days');
  const requestedGap = (rawGap === null ? 1 : Number(rawGap)) as SignalGapDays;

  return {
    profiles,
    gapDays: VALID_GAPS.has(requestedGap) ? requestedGap : 1,
  };
}

function sameSelection(left: string[], right: string[]): boolean {
  if (left.length !== right.length) return false;
  const rightSet = new Set(right);
  return left.every((profile) => rightSet.has(profile));
}

const SpySignals: React.FC = () => {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const serializedSearchParams = searchParams.toString();
  const [draftProfiles, setDraftProfiles] = useState<string[]>([]);
  const [draftGap, setDraftGap] = useState<SignalGapDays>(1);
  const [appliedProfiles, setAppliedProfiles] = useState<string[]>([]);
  const [appliedGap, setAppliedGap] = useState<SignalGapDays>(1);

  const { isAdmin, isGlobalAdminView, effectiveScope } = useAdminScope();
  const {
    data: profiles,
    isLoading: profilesLoading,
    error: profilesError,
  } = useScopedProfiles();

  const rewatchEchoesQuery = useQuery({
    queryKey: ['rewatch-echoes', [...appliedProfiles].sort(), appliedGap],
    queryFn: () => spySignalsApi.getRewatchEchoes(appliedProfiles, appliedGap),
    enabled: appliedProfiles.length >= 2,
    staleTime: 2 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const profilesArray = useMemo(
    () => Array.isArray(profiles)
      ? profiles.filter((profile) => profile.scraping_status === 'completed')
      : [],
    [profiles],
  );

  useEffect(() => {
    if (profilesArray.length === 0) return;

    const queryState = readQueryState(new URLSearchParams(serializedSearchParams));
    const availableProfiles = new Map(
      profilesArray.map((profile) => [profile.username.toLocaleLowerCase(), profile.username]),
    );
    const requestedProfiles = Array.from(
      new Map(
        queryState.profiles
          .map((profile) => availableProfiles.get(profile.trim().toLocaleLowerCase()))
          .filter((profile): profile is string => Boolean(profile))
          .map((profile) => [profile.toLocaleLowerCase(), profile]),
      ).values(),
    );
    const initialProfiles = requestedProfiles.length >= 2
      ? requestedProfiles
      : profilesArray.map((profile) => profile.username);

    setDraftProfiles((current) => sameSelection(current, initialProfiles) ? current : initialProfiles);
    setAppliedProfiles((current) => sameSelection(current, initialProfiles) ? current : initialProfiles);
    setDraftGap((current) => current === queryState.gapDays ? current : queryState.gapDays);
    setAppliedGap((current) => current === queryState.gapDays ? current : queryState.gapDays);
  }, [profilesArray, serializedSearchParams]);

  // The empty-list "all profiles" shorthand expands server-side to the caller's
  // default set: everything for admins, the tracked set otherwise. An admin in
  // the tracked view must therefore always send the selection explicitly.
  const allProfilesSelected = appliedProfiles.length === profilesArray.length;
  const canUseServerDefault = allProfilesSelected && (!isAdmin || isGlobalAdminView);

  const {
    data: signals,
    isLoading: signalsLoading,
    isFetching: signalsFetching,
    error: signalsError,
    refetch: refetchSignals,
  } = useQuery({
    queryKey: [
      'spy-signals',
      'events',
      effectiveScope,
      allProfilesSelected ? 'all' : [...appliedProfiles].sort(),
      appliedGap,
    ],
    queryFn: () => spySignalsApi.getSignals(
      canUseServerDefault ? [] : appliedProfiles,
      appliedGap,
    ),
    enabled: appliedProfiles.length >= 2,
    staleTime: 2 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const handleScan = () => {
    if (draftProfiles.length < 2) return;

    const wasAlreadyApplied = sameSelection(draftProfiles, appliedProfiles) && draftGap === appliedGap;
    setAppliedProfiles([...draftProfiles]);
    setAppliedGap(draftGap);

    const params = new URLSearchParams();
    if (draftProfiles.length !== profilesArray.length) {
      draftProfiles.forEach((profile) => params.append('profiles', profile));
    }
    params.set('gap_days', String(draftGap));
    router.replace(`${pathname}?${params.toString()}`, { scroll: false });

    if (wasAlreadyApplied) {
      void Promise.all([refetchSignals(), rewatchEchoesQuery.refetch()]);
    }
  };

  return (
    <motion.div
      className="space-y-6"
      initial={{ y: 18 }}
      animate={{ y: 0 }}
      transition={{ duration: 0.5 }}
    >
      <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-4xl font-bold text-white text-glow">Spy Signals</h1>
          <p className="mt-2 max-w-3xl text-white/60">
            Find people who watched the same film on the same day or within a chosen time gap.
          </p>
        </div>
        <div className="lg:hidden"><AdminScopeToggle /></div>
      </header>

      {profilesLoading ? (
        <LoadingSpinner message="Loading monitored profiles..." />
      ) : profilesError ? (
        <ErrorMessage message="Failed to load profiles for signal scanning." />
      ) : profilesArray.length < 2 ? (
        <section className="card-cinema flex min-h-72 flex-col items-center justify-center text-center">
          <span className="rounded-2xl border border-cinema-400/25 bg-cinema-500/10 p-4 text-cinema-400">
            <Radar className="h-8 w-8" />
          </span>
          <h2 className="mt-5 text-xl font-semibold text-white">Two profiles are needed</h2>
          <p className="mt-2 max-w-md text-sm leading-6 text-white/55">
            Add or request at least two Letterboxd profiles in My Profiles before scanning for co-watch behavior.
          </p>
          <Link href="/profiles" className="btn-primary mt-5 px-5 py-2 text-sm">Open My Profiles</Link>
        </section>
      ) : (
        <>
          <SpySignalsControls
            profiles={profilesArray}
            selectedProfiles={draftProfiles}
            gapDays={draftGap}
            isScanning={signalsFetching}
            onSelectionChange={setDraftProfiles}
            onGapChange={setDraftGap}
            onScan={handleScan}
          />

          {signalsLoading ? (
            <LoadingSpinner message="Scanning watch histories for matching signals..." />
          ) : signalsError ? (
            <section className="card-cinema flex min-h-64 flex-col items-center justify-center text-center">
              <span className="rounded-xl border border-red-400/30 bg-red-500/10 p-3 text-red-300">
                <AlertTriangle className="h-6 w-6" />
              </span>
              <h2 className="mt-4 text-lg font-semibold text-white">Signal scan failed</h2>
              <p className="mt-2 max-w-md text-sm text-white/50">
                The selected profiles could not be compared. Check the API connection and try again.
              </p>
              <button type="button" onClick={() => void refetchSignals()} className="btn-secondary mt-5 px-5 py-2 text-sm">
                Try Again
              </button>
            </section>
          ) : signals ? (
            <>
              <SpySignalsResults
                groupSignals={signals.group_signals}
                gapDays={signals.gap_days as SignalGapDays}
                selectedProfileCount={signals.selected_profiles.length}
              />
              <RewatchEchoesPanel
                data={rewatchEchoesQuery.data}
                loading={rewatchEchoesQuery.isLoading}
                error={Boolean(rewatchEchoesQuery.error)}
                onRetry={() => void rewatchEchoesQuery.refetch()}
              />
            </>
          ) : null}
        </>
      )}
    </motion.div>
  );
};

export default SpySignals;
