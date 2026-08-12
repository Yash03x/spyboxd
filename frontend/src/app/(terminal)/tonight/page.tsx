'use client';

import { Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';

import TerminalShell from '../../../components/terminal/TerminalShell';
import SelectionBar from '../../../components/terminal/SelectionBar';
import { getSection, getTab } from '../../../components/terminal/sections';
import { useTerminalSelection } from '../../../hooks/useTerminalSelection';
import { insightsApi } from '../../../services/api';
import AvailabilityTab from '../../../views/tonight/AvailabilityTab';
import ListsTab from '../../../views/tonight/ListsTab';
import PicksTab from '../../../views/tonight/PicksTab';

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

  const controls = (
    <SelectionBar
      profiles={selection.available}
      selected={selection.selected}
      hrefFor={selection.toggleHref}
      isLocked={selection.isLockedByMinimum}
    >
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
