'use client';

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';

import TerminalShell from '../../../components/terminal/TerminalShell';
import SelectionBar from '../../../components/terminal/SelectionBar';
import { getSection, getTab } from '../../../components/terminal/sections';
import { useTerminalSelection } from '../../../hooks/useTerminalSelection';
import CircleTab from '../../../views/people/CircleTab';
import OnePersonTab from '../../../views/people/OnePersonTab';
import ReachTab from '../../../views/people/ReachTab';
import TwoPeopleTab from '../../../views/people/TwoPeopleTab';

function PeopleSection() {
  const section = getSection('people');
  const searchParams = useSearchParams();
  const tab = getTab(section, searchParams.get('tab'));

  // One person and The circle are about a single subject; Two people compares
  // the first two of the selection. Both live in the URL so any view of this
  // section is linkable.
  const selection = useTerminalSelection({
    minSelection: 1,
    defaultCount: tab.id === 'two' ? 2 : undefined,
  });

  const requested = searchParams.get('subject');
  const subject =
    selection.available.find((name) => name.toLowerCase() === (requested ?? '').toLowerCase()) ??
    selection.selected[0] ??
    selection.available[0] ??
    '';

  const subjectHref = (username: string) => selection.paramHref('subject', username);
  const isPair = tab.id === 'two';
  const singleSubject = tab.id === 'one' || tab.id === 'circle';

  const controls = singleSubject ? (
    <SelectionBar
      label="SUBJECT"
      profiles={selection.available}
      selected={subject ? [subject] : []}
      hrefFor={subjectHref}
    />
  ) : (
    <SelectionBar
      profiles={selection.available}
      selected={isPair ? selection.selected.slice(0, 2) : selection.selected}
      hrefFor={isPair ? selection.pairHref : selection.toggleHref}
      isLocked={isPair ? undefined : selection.isLockedByMinimum}
    />
  );

  return (
    <TerminalShell section={section} tabId={tab.id} controls={controls}>
      {tab.id === 'one' ? <OnePersonTab subject={subject} /> : null}
      {tab.id === 'two' ? <TwoPeopleTab profiles={selection.selected} /> : null}
      {tab.id === 'circle' ? (
        <CircleTab subject={subject} profiles={selection.available} subjectHref={subjectHref} />
      ) : null}
      {tab.id === 'reach' ? <ReachTab subject={subject} profiles={selection.selected} /> : null}
    </TerminalShell>
  );
}

export default function PeoplePage() {
  return (
    <Suspense fallback={null}>
      <PeopleSection />
    </Suspense>
  );
}
