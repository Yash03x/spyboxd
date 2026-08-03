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

function RegionPicker({
  value,
  regions,
  hrefFor,
}: {
  value: string;
  regions: string[];
  hrefFor: (region: string) => string;
}) {
  if (regions.length < 2) return null;
  return (
    <div className="flex items-center gap-2">
      <span className="text-t9 tracking-tab text-term-muted2">REGION</span>
      <div className="flex items-center gap-1">
        {regions.map((region) => {
          const active = region === value;
          return (
            <a
              key={region}
              href={hrefFor(region)}
              aria-current={active ? 'true' : undefined}
              className="rounded-[3px] border px-2 py-[3px] text-t10 no-underline hover:no-underline"
              style={{
                borderColor: active ? 'var(--accent)' : 'var(--rule)',
                background: active
                  ? 'color-mix(in srgb, var(--accent) 14%, transparent)'
                  : 'transparent',
                color: active ? 'var(--accent)' : 'var(--muted)',
              }}
            >
              {region}
            </a>
          );
        })}
      </div>
    </div>
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

  const available = (regionsQuery.data?.regions ?? []).map((entry) => entry.code);
  const region =
    searchParams.get('region') ?? regionsQuery.data?.default_region ?? available[0] ?? 'IN';

  const controls = (
    <SelectionBar
      profiles={selection.available}
      selected={selection.selected}
      hrefFor={selection.toggleHref}
      isLocked={selection.isLockedByMinimum}
    >
      <RegionPicker
        value={region}
        regions={available.slice(0, 6)}
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
