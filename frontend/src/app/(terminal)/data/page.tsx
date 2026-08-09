'use client';

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';

import TerminalShell from '../../../components/terminal/TerminalShell';
import SelectionBar from '../../../components/terminal/SelectionBar';
import { getSection, getTab } from '../../../components/terminal/sections';
import { useTerminalSelection } from '../../../hooks/useTerminalSelection';
import LostFoundTab from '../../../views/data/LostFoundTab';
import MissingTab from '../../../views/data/MissingTab';
import ProfilesTab from '../../../views/data/ProfilesTab';
import RefreshesTab from '../../../views/data/RefreshesTab';

function DataSection() {
  const section = getSection('data');
  const searchParams = useSearchParams();
  const tab = getTab(section, searchParams.get('tab'));
  // Every synced profile by default, not the usual six. This section's
  // question is "where did all this come from" and its panels are titled as
  // totalities -- EVERYONE WE HAVE SYNCED sat six rows long directly above a
  // library panel counting twenty, two panels on one tab disagreeing about
  // the roster. A comparison tab caps its default because comparing twenty
  // people is unreadable; an inventory has no such excuse.
  const selection = useTerminalSelection({ minSelection: 1, defaultCount: Number.MAX_SAFE_INTEGER });

  const controls = (
    <SelectionBar
      profiles={selection.available}
      selected={selection.selected}
      hrefFor={selection.toggleHref}
      isLocked={selection.isLockedByMinimum}
    />
  );

  return (
    <TerminalShell section={section} tabId={tab.id} controls={controls}>
      {tab.id === 'profiles' ? (
        <ProfilesTab profiles={selection.selected} selectionLoading={selection.isLoading} />
      ) : null}
      {tab.id === 'refreshes' ? <RefreshesTab profiles={selection.selected} selectionLoading={selection.isLoading} /> : null}
      {tab.id === 'missing' ? <MissingTab profiles={selection.selected} selectionLoading={selection.isLoading} /> : null}
      {tab.id === 'lost' ? <LostFoundTab profiles={selection.selected} selectionLoading={selection.isLoading} /> : null}
    </TerminalShell>
  );
}

export default function DataPage() {
  return (
    <Suspense fallback={null}>
      <DataSection />
    </Suspense>
  );
}
