'use client';

import React from 'react';
import Rail from './Rail';
import StatusBar from './StatusBar';
import TabRow from './TabRow';
import ExploreGuide from './ExploreGuide';
import SavedWorkspace from './SavedWorkspace';
import { getTab, type SectionDef } from './sections';

export interface TerminalShellProps {
  section: SectionDef;
  /** The resolved `?tab=` value. */
  tabId?: string | null;
  /**
   * Controls that recompute every panel on the tab -- the profile selection,
   * the closeness tier. Rendered as a bar under the tab row rather than as a
   * panel, because it is not an answer to anything.
   */
  controls?: React.ReactNode;
  children: React.ReactNode;
}

/**
 * The shell: rail, status bar, section header, tab row, panel grid.
 *
 * There is deliberately no entrance animation anywhere in here. Opacity
 * multiplies down a tree, so a shell that fades itself in makes the whole
 * app's visibility depend on an animation clock -- and a background tab
 * freezes that clock at 0%, which reads as a blank page rather than as a
 * missing flourish.
 */
export default function TerminalShell({ section, tabId, controls, children }: TerminalShellProps) {
  const tab = getTab(section, tabId);

  return (
    <div className="terminal-root flex min-h-screen items-stretch pb-[64px] md:pb-0">
      <a href="#main-content" className="sr-only z-[100] rounded bg-term-bg px-4 py-3 text-term-accent focus:not-sr-only focus:fixed focus:left-2 focus:top-2">Skip to insights</a>
      <Rail active={section.id} />

      <div className="flex min-w-0 flex-1 flex-col">
        <StatusBar section={section} tab={tab} />

        <header className="px-[14px] pt-[14px]">
          <div className="flex flex-wrap items-baseline gap-[10px]">
            <h1 className="m-0 font-term-sans text-t20 font-bold tracking-head text-term-ink">
              {section.name}
            </h1>
            <span className="font-term-sans text-t11 text-term-muted">{section.question}</span>
          </div>
          <p className="m-0 mt-[6px] max-w-[54rem] font-term-sans text-t115 text-term-ink3">
            {section.blurb}
          </p>
          <ExploreGuide />
          <SavedWorkspace />
        </header>

        <TabRow section={section} active={tab} />

        {controls}

        <main
          id="main-content"
          tabIndex={-1}
          className="grid items-start gap-3 p-[14px]"
          style={{ gridTemplateColumns: 'repeat(auto-fit,minmax(min(400px,100%),1fr))' }}
        >
          {children}
        </main>

        <div className="px-[14px] pb-[18px]">
          <p className="m-0 max-w-[60rem] font-term-sans text-t10 text-term-dim">
            {section.id === 'anime' ? 'Anime insights use your private uploaded snapshot. Dates describe list entries, not an episode-by-episode viewing history. Source & Data Quality explains the limits.' : 'Insights describe recorded public-profile activity, not proof that people watched together or influenced one another. Source notes and Data explain coverage and freshness.'}
          </p>
        </div>
      </div>
    </div>
  );
}
