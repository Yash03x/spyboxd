'use client';

import Link from 'next/link';
import { usePathname, useSearchParams } from 'next/navigation';
import React from 'react';
import type { SectionDef, TabDef } from './sections';

/**
 * Sticky under the status bar. Tabs are links carrying `?tab=`, not local
 * state, so every tab in the product is linkable and survives a reload.
 */
export default function TabRow({ section, active }: { section: SectionDef; active: TabDef }) {
  const pathname = usePathname();
  const searchParams = useSearchParams();

  if (section.tabs.length < 2) return null;

  const hrefFor = (tab: TabDef) => {
    // Everything else in the query string -- the profile selection, the
    // subject, the region -- has to survive a tab change.
    const params = new URLSearchParams(searchParams.toString());
    params.set('tab', tab.id);
    return `${pathname}?${params.toString()}`;
  };

  return (
    <div
      role="tablist"
      // The status bar is one 34px row only from `md` up; below that it
      // wraps onto a second line and is roughly 60px tall, so pinning the
      // tabs at 34px slid them under it on a phone. Not sticky at all
      // below `md`: the wrapped bar already eats enough of a small
      // viewport without a second fixed strip under it.
      className="z-40 mt-3 flex items-stretch overflow-x-auto border-b border-term-rule bg-term-bg px-[14px] md:sticky md:top-[34px]"
    >
      {section.tabs.map((tab) => {
        const isActive = tab.id === active.id;
        return (
          <Link
            key={tab.id}
            href={hrefFor(tab)}
            role="tab"
            aria-selected={isActive}
            scroll={false}
            className="relative shrink-0 px-4 pb-[9px] pt-2 font-term text-t11 font-bold tracking-tab no-underline hover:no-underline"
            style={{ color: isActive ? 'var(--accent)' : 'var(--muted)' }}
          >
            {tab.label}
            <span className="ml-[7px] text-t95 font-normal text-term-dim">{tab.panels}</span>
            <span
              className="absolute inset-x-0 bottom-[-1px] h-[2px]"
              style={{ background: isActive ? 'var(--accent)' : 'transparent' }}
            />
          </Link>
        );
      })}
    </div>
  );
}
