'use client';

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';

import TerminalShell from '../../../components/terminal/TerminalShell';
import SelectionBar from '../../../components/terminal/SelectionBar';
import { getSection, getTab } from '../../../components/terminal/sections';
import { useTerminalSelection } from '../../../hooks/useTerminalSelection';
import GapsTab from '../../../views/films/GapsTab';
import LibraryTab from '../../../views/films/LibraryTab';
import TasteMapTab from '../../../views/films/TasteMapTab';

function FilmsSection() {
  const section = getSection('films');
  const searchParams = useSearchParams();
  const tab = getTab(section, searchParams.get('tab'));
  // Films is about a library rather than a comparison, so one profile is a
  // perfectly good selection here.
  const selection = useTerminalSelection({ minSelection: 1 });

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
      {tab.id === 'library' ? <LibraryTab profiles={selection.selected} /> : null}
      {tab.id === 'taste' ? <TasteMapTab profiles={selection.selected} /> : null}
      {tab.id === 'gaps' ? <GapsTab profiles={selection.selected} /> : null}
    </TerminalShell>
  );
}

export default function FilmsPage() {
  return (
    <Suspense fallback={null}>
      <FilmsSection />
    </Suspense>
  );
}
