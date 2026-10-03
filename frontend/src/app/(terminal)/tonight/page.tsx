'use client';

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';

import TerminalShell from '../../../components/terminal/TerminalShell';
import SelectionBar from '../../../components/terminal/SelectionBar';
import { getSection, getTab } from '../../../components/terminal/sections';
import { useTerminalSelection } from '../../../hooks/useTerminalSelection';
import { insightsApi } from '../../../services/api';
import AvailabilityTab from '../../../views/tonight/AvailabilityTab';
import ListsTab from '../../../views/tonight/ListsTab';
import PicksTab from '../../../views/tonight/PicksTab';
import PickFilters, { readPickPreferences } from '../../../views/tonight/PickFilters';

const countryNames = new Intl.DisplayNames(['en'], { type: 'region' });

function RegionPicker({
  value,
  regions,
  worldwideRegion,
  onChange,
  pending,
}: {
  value: string;
  regions: string[];
  worldwideRegion: string;
  onChange: (region: string) => void;
  pending: boolean;
}) {
  if (regions.length < 2) return null;
  return (
    <label className="flex max-w-full flex-wrap items-center gap-2 text-t9 tracking-tab text-term-muted2">
      AVAILABILITY COUNTRY
      <select
        aria-label="Availability country"
        value={value}
        disabled={pending}
        onChange={(event) => onChange(event.target.value)}
        className="min-w-0 max-w-full rounded-[3px] border border-term-rule bg-term-bg px-2 py-[3px] font-term text-t10 tracking-normal text-term-ink3 sm:max-w-[15rem]"
      >
        {regions.map((region) => (
          <option key={region} value={region}>
            {region === worldwideRegion ? 'Worldwide (any supported country)' : `${countryNames.of(region) ?? region} (${region})`}
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
  const preferences = readPickPreferences(searchParams);
  const controlsPending = selection.isLoading || !selection.isInitialized;
  // Clearing preferences must not depend on the profile catalog finishing its
  // initial request, or an early click after reload can erase the chosen group.
  const resetParams = new URLSearchParams(searchParams.toString());
  ['max_runtime', 'genre', 'availability', 'rewatch', 'pick'].forEach((key) => resetParams.delete(key));
  const resetHref = `/tonight${resetParams.size ? `?${resetParams}` : ''}`;
  const updatePreference = (key: string, value: string) => {
    // These controls change client queries, not the server-rendered route.
    // Next synchronizes native history with useSearchParams. Reading the live
    // URL also preserves earlier changes when controls are used in quick succession.
    const next = new URLSearchParams(window.location.search);
    next.delete('pick');
    next.delete('profiles');
    selection.selected.forEach((profile) => next.append('profiles', profile));
    if (value) next.set(key, value);
    else next.delete(key);
    window.history.pushState(null, '', `/tonight?${next}`);
  };

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
    <>
    <SelectionBar
      profiles={selection.available}
      selected={selection.selected}
      hrefFor={selection.toggleHref}
      groupHrefFor={selection.urlFor}
      isLocked={selection.isLockedByMinimum}
    >
      <RegionPicker
        value={region}
        regions={regionOptions}
        worldwideRegion={worldwideRegion}
        onChange={(next) => updatePreference('region', next)}
        pending={controlsPending}
      />
    </SelectionBar>
    {tab.id === 'picks' ? (
      <PickFilters
        value={preferences}
        onChange={updatePreference}
        resetHref={resetHref}
        pending={controlsPending}
      />
    ) : null}
    </>
  );

  return (
    <TerminalShell section={section} tabId={tab.id} controls={controls}>
      {tab.id === 'picks' ? (
        <PicksTab
          profiles={selection.selected}
          region={region}
          pick={searchParams.get('pick')}
          pickHref={(id) => selection.paramHref('pick', id)}
          preferences={preferences}
          resetHref={resetHref}
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
