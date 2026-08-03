'use client';

import Link from 'next/link';
import { Suspense } from 'react';

import Panel from '../../../components/terminal/Panel';
import Rows, { cell } from '../../../components/terminal/bodies/Rows';
import Notes from '../../../components/terminal/bodies/Notes';
import StatusBar from '../../../components/terminal/StatusBar';
import Rail from '../../../components/terminal/Rail';
import { SECTIONS, getSection } from '../../../components/terminal/sections';

const REPLACED: Record<string, string> = {
  overview: 'My Dashboard',
  overlaps: 'Spy Signals',
  people: 'Analysis + Compare + Network',
  tonight: 'Watch Together',
  films: 'new',
  data: 'My Profiles',
};

function ArchitectureMap() {
  const section = getSection('overview');
  const totalPanels = SECTIONS.reduce(
    (sum, entry) => sum + entry.tabs.reduce((tabs, tab) => tabs + tab.panels, 0),
    0,
  );
  const totalTabs = SECTIONS.reduce((sum, entry) => sum + entry.tabs.length, 0);

  return (
    <div className="terminal-root flex min-h-screen items-stretch pb-[52px] md:pb-0">
      <Rail active="overview" />
      <div className="flex min-w-0 flex-1 flex-col">
        <StatusBar section={section} tab={{ id: 'map', label: 'ARCHITECTURE MAP', panels: 0 }} />

        <header className="px-[14px] pt-[14px]">
          <div className="flex flex-wrap items-baseline gap-[10px]">
            <h1 className="m-0 font-term-sans text-t20 font-bold tracking-head text-term-ink">
              Architecture map
            </h1>
            <span className="font-term-sans text-t11 text-term-muted">
              Where did everything go?
            </span>
          </div>
          <p className="m-0 mt-[6px] max-w-[54rem] font-term-sans text-t115 text-term-ink3">
            Six question-named sections replaced eight feature-named destinations. Nothing was
            dropped — every panel that existed has a named home below.
          </p>
        </header>

        <div
          className="mt-3 grid items-start gap-3 p-[14px]"
          style={{ gridTemplateColumns: 'repeat(auto-fit,minmax(min(400px,100%),1fr))' }}
        >
          <Panel
            title="THE SIX SECTIONS"
            src="components/terminal/sections.ts"
            wide
            stats={[
              { big: SECTIONS.length, unit: 'SECTIONS', tone: 'var(--accent)' },
              { big: totalTabs, unit: 'TABS' },
              { big: totalPanels, unit: 'PANELS' },
            ]}
            caveat="A section whose rail icon still points at an old path has not been moved across yet. The link goes somewhere that works rather than somewhere that does not exist."
          >
            <Rows
              columns="26px minmax(0,0.7fr) minmax(0,1.2fr) minmax(0,1fr) 60px"
              head={['#', 'SECTION', 'QUESTION IT ANSWERS', 'REPLACES', ['PANELS', 'right']]}
              rows={SECTIONS.map((entry) => {
                const panels = entry.tabs.reduce((sum, tab) => sum + tab.panels, 0);
                return {
                  href: entry.legacyPath ?? `/${entry.id}`,
                  cells: [
                    cell(entry.ordinal, { size: '10px', tone: 'var(--muted)' }),
                    cell(entry.name, { font: 's', size: '11.5px', tone: 'var(--ink)' }),
                    cell(entry.question, { font: 's', size: '10.5px', wrap: true }),
                    cell(REPLACED[entry.id] ?? '—', {
                      font: 's',
                      size: '10px',
                      tone: 'var(--dim)',
                      wrap: true,
                    }),
                    cell(String(panels), { align: 'right', tone: 'var(--accent)' }),
                  ],
                };
              })}
            />
          </Panel>

          {SECTIONS.map((entry) => (
            <Panel
              key={entry.id}
              title={`${entry.ordinal} ${entry.name.toUpperCase()}`}
              src={entry.legacyPath ? `still at ${entry.legacyPath}` : `/${entry.id}`}
              blurb={entry.blurb}
            >
              <Rows
                columns="minmax(0,1fr) 60px"
                head={['TAB', ['PANELS', 'right']]}
                rows={entry.tabs.map((tab) => ({
                  href: entry.legacyPath ?? `/${entry.id}?tab=${tab.id}`,
                  cells: [
                    cell(tab.label, { size: '10.5px', tone: 'var(--ink2)' }),
                    cell(String(tab.panels), { align: 'right', tone: 'var(--accent)' }),
                  ],
                }))}
              />
            </Panel>
          ))}

          <Panel title="WHAT THE REDESIGN DOES NOT CLAIM" src="the data ceiling" wide>
            <Notes
              items={[
                {
                  label: 'When a rating was given',
                  text: 'Ratings carry a watch date, never a rating timestamp. "Rated it after their friend did" is unprovable and would be invention.',
                },
                {
                  label: 'Time of day',
                  text: 'Diary entries carry a date, not a clock. This is why the weekday panel stops at weekday.',
                },
                {
                  label: 'A second read of the same surface',
                  text: 'Change detection needs two authoritative snapshots. A first import is a baseline and emits nothing; several panels stay empty by design until a profile is refreshed twice, and they say so.',
                },
                {
                  label: 'Owner consent',
                  text: 'Likes, comments, pronouns and deleted history exist only in an official export. No amount of public scraping reaches them.',
                },
                {
                  label: 'When a film leaves a service',
                  text: 'The provider feed publishes what carries a film today and nothing about when that stops. A countdown would be a guess wearing a number’s clothes.',
                },
              ]}
            />
          </Panel>
        </div>

        <div className="px-[14px] pb-[18px]">
          <p className="m-0 max-w-[60rem] font-term-sans text-t10 text-term-dim">
            <Link href="/overview">Back to Overview</Link>
          </p>
        </div>
      </div>
    </div>
  );
}

export default function ArchitecturePage() {
  return (
    <Suspense fallback={null}>
      <ArchitectureMap />
    </Suspense>
  );
}
