'use client';

import { Suspense } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';

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
  const router = useRouter();
  const pathname = usePathname();
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

  // Pushed rather than replaced: re-centring the graph on somebody is a
  // navigation, and Back has to return to who you were looking at before.
  const setSubject = (username: string) => {
    const params = new URLSearchParams(searchParams.toString());
    params.set('subject', username);
    router.push(`${pathname}?${params.toString()}`, { scroll: false });
  };

  const singleSubject = tab.id === 'one' || tab.id === 'circle';

  const togglePair = (username: string) => {
    const current = selection.selected;
    if (current[0] === username) return;
    if (current.includes(username)) {
      selection.applyProfiles([current[0], ...current.filter((name) => name !== username)].slice(0, 2));
      return;
    }
    selection.applyProfiles([current[0] ?? username, username].slice(0, 2));
  };

  const controls = singleSubject ? (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-term-rule bg-term-bg2 px-[14px] py-[7px]">
      <span className="text-t9 tracking-tab text-term-muted2">SUBJECT</span>
      <div className="flex flex-wrap items-center gap-1">
        {selection.available.map((username) => {
          const active = username.toLowerCase() === subject.toLowerCase();
          return (
            <button
              key={username}
              type="button"
              onClick={() => setSubject(username)}
              aria-pressed={active}
              className="rounded-[3px] border px-2 py-[3px] text-t10"
              style={{
                borderColor: active ? 'var(--accent)' : 'var(--rule)',
                background: active
                  ? 'color-mix(in srgb, var(--accent) 14%, transparent)'
                  : 'transparent',
                color: active ? 'var(--accent)' : 'var(--muted)',
              }}
            >
              @{username}
            </button>
          );
        })}
      </div>
    </div>
  ) : (
    <SelectionBar
      profiles={selection.available}
      selected={tab.id === 'two' ? selection.selected.slice(0, 2) : selection.selected}
      onToggle={tab.id === 'two' ? togglePair : selection.toggle}
      minSelection={tab.id === 'two' ? 1 : 1}
    />
  );

  return (
    <TerminalShell section={section} tabId={tab.id} controls={controls}>
      {tab.id === 'one' ? <OnePersonTab subject={subject} /> : null}
      {tab.id === 'two' ? <TwoPeopleTab profiles={selection.selected} /> : null}
      {tab.id === 'circle' ? (
        <CircleTab
          subject={subject}
          profiles={selection.available}
          onSubjectChange={setSubject}
        />
      ) : null}
      {tab.id === 'reach' ? (
        <ReachTab subject={subject} profiles={selection.selected} />
      ) : null}
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
