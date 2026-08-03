'use client';

import React from 'react';
import Rail from './Rail';
import StatusBar from './StatusBar';
import TabRow from './TabRow';
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
    <div className="terminal-root flex min-h-screen items-stretch pb-[52px] md:pb-0">
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
        </header>

        <TabRow section={section} active={tab} />

        {controls}

        <div
          className="grid items-start gap-3 p-[14px]"
          style={{ gridTemplateColumns: 'repeat(auto-fit,minmax(min(400px,100%),1fr))' }}
        >
          {children}
        </div>

        <div className="px-[14px] pb-[18px]">
          <p className="m-0 max-w-[60rem] font-term-sans text-t10 text-term-dim">
            Panels bordered in amber are new in this redesign. The SRC line on each header names the
            table it reads, so nothing here is a claim without a source.
          </p>
        </div>
      </div>
    </div>
  );
}
