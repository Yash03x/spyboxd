'use client';

import { Suspense } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';

import TerminalShell from '../../../components/terminal/TerminalShell';
import SelectionBar from '../../../components/terminal/SelectionBar';
import { getSection, getTab } from '../../../components/terminal/sections';
import { useTerminalSelection } from '../../../hooks/useTerminalSelection';
import { insightsApi } from '../../../services/api';
import AvailabilityTab from '../../../views/tonight/AvailabilityTab';
import ListsTab from '../../../views/tonight/ListsTab';
import PicksTab, { type TonightPickMode } from '../../../views/tonight/PicksTab';

const PICK_MODES: ReadonlyArray<{
  value: TonightPickMode;
  label: string;
  description: string;
}> = [
  {
    value: 'watchlist_overlap',
    label: 'WATCHLIST FIT',
    description: 'Rank everything queued by somebody in the room.',
  },
  {
    value: 'unseen_pick',
    label: 'UNSEEN BY ALL',
    description: 'Only show films nobody selected has watched.',
  },
  {
    value: 'collective_blind_spots',
    label: 'ONE PERSON LOVES',
    description: 'Start from a film one person loved and everyone else has yet to see.',
  },
];

const PICK_MODE_VALUES = new Set<TonightPickMode>(PICK_MODES.map((option) => option.value));

function PickModePicker({
  value,
  hrefFor,
}: {
  value: TonightPickMode;
  hrefFor: (mode: TonightPickMode) => string;
}) {
  return (
    <div role="group" aria-label="Pick decision" className="flex flex-wrap items-center gap-2">
      <span className="text-t9 tracking-tab text-term-muted2">DECISION</span>
      <div className="flex flex-wrap items-center gap-1">
        {PICK_MODES.map((option) => {
          const active = option.value === value;
          return (
            <Link
              key={option.value}
              href={hrefFor(option.value)}
              scroll={false}
              aria-current={active ? 'true' : undefined}
              title={option.description}
              className="rounded-[3px] border px-2 py-[3px] text-t10 no-underline hover:no-underline"
              style={{
                borderColor: active ? 'var(--accent)' : 'var(--rule)',
                background: active
                  ? 'color-mix(in srgb, var(--accent) 14%, transparent)'
                  : 'transparent',
                color: active ? 'var(--accent)' : 'var(--muted)',
              }}
            >
              {option.label}
            </Link>
          );
        })}
      </div>
    </div>
  );
}

function RegionPicker({
  value,
  regions,
  worldwideRegion,
  hrefFor,
}: {
  value: string;
  regions: string[];
  worldwideRegion: string;
  hrefFor: (region: string) => string;
}) {
  const router = useRouter();
  if (regions.length < 2) return null;
  return (
    <label className="flex items-center gap-2 text-t9 tracking-tab text-term-muted2">
      AVAILABILITY COUNTRY
      <select
        aria-label="Availability country"
        value={value}
        onChange={(event) => router.replace(hrefFor(event.target.value), { scroll: false })}
        className="max-w-[15rem] rounded-[3px] border border-term-rule bg-term-bg px-2 py-[3px] font-term text-t10 tracking-normal text-term-ink3"
      >
        {regions.map((region) => (
          <option key={region} value={region}>
            {region === worldwideRegion ? 'Worldwide (any supported availability country)' : region}
          </option>
        ))}
      </select>
    </label>
  );
}

function TonightSection() {
  const section = getSection('tonight');
  const searchParams = useSearchParams();
  const tab = getTab(section, searchParams.get('tab'));
  const selection = useTerminalSelection({ minSelection: 1 });

  const regionsQuery = useQuery({
    queryKey: ['watch-provider-regions'],
    queryFn: () => insightsApi.getWatchProviderRegions(),
    staleTime: 30 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const available = (regionsQuery.data?.regions ?? []).map((entry) => entry.code.toUpperCase());
  const worldwideRegion = regionsQuery.data?.worldwide_region?.toUpperCase() ?? 'ALL';
  const requestedRegion = searchParams.get('region')?.trim().toUpperCase();
  const validRequestedRegion = requestedRegion === worldwideRegion || /^[A-Z]{2}$/.test(requestedRegion ?? '');
  const region = validRequestedRegion
    ? requestedRegion!
    : regionsQuery.data?.default_region?.toUpperCase() ?? worldwideRegion ?? available[0] ?? 'ALL';
  // `regions` contains countries backed by cached provider data; the API's
  // Worldwide sentinel is separate. Keep every country selectable instead of
  // silently dropping everything after the first six, and retain a valid deep
  // link so the API can honestly say that country has never been read.
  const regionOptions = Array.from(new Set([
    worldwideRegion,
    ...(validRequestedRegion ? [requestedRegion!] : []),
    ...available,
  ]));
  const requestedMode = searchParams.get('mode')?.trim() as TonightPickMode | undefined;
  const mode = requestedMode && PICK_MODE_VALUES.has(requestedMode)
    ? requestedMode
    : 'watchlist_overlap';

  const controls = (
    <SelectionBar
      profiles={selection.available}
      selected={selection.selected}
      hrefFor={selection.toggleHref}
      isLocked={selection.isLockedByMinimum}
    >
      {tab.id === 'picks' ? (
        <PickModePicker
          value={mode}
          hrefFor={(next) => selection.paramHref('mode', next)}
        />
      ) : null}
      <RegionPicker
        value={region}
        regions={regionOptions}
        worldwideRegion={worldwideRegion}
        hrefFor={(next) => selection.paramHref('region', next)}
      />
    </SelectionBar>
  );

  return (
    <TerminalShell section={section} tabId={tab.id} controls={controls}>
      {tab.id === 'picks' ? (
        <PicksTab
          profiles={selection.selected}
          region={region}
          mode={mode}
          pick={searchParams.get('pick')}
          pickHref={(title) => selection.paramHref('pick', title)}
        />
      ) : null}
      {tab.id === 'lists' ? <ListsTab profiles={selection.selected} /> : null}
      {tab.id === 'leaving' ? (
        <AvailabilityTab profiles={selection.selected} region={region} />
      ) : null}
    </TerminalShell>
  );
}

export default function TonightPage() {
  return (
    <Suspense fallback={null}>
      <TonightSection />
    </Suspense>
  );
}
