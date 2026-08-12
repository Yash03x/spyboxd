'use client';

import Link from 'next/link';
import React from 'react';

const CHIP_BASE = 'rounded-[3px] border px-2 py-[3px] text-t10 no-underline hover:no-underline';

function chipStyle(active: boolean): React.CSSProperties {
  return {
    borderColor: active ? 'var(--accent)' : 'var(--rule)',
    background: active ? 'color-mix(in srgb, var(--accent) 14%, transparent)' : 'transparent',
    color: active ? 'var(--accent)' : 'var(--muted)',
  };
}

export interface SelectionBarProps {
  label?: string;
  profiles: string[];
  selected: string[];
  /**
   * Where clicking a chip goes. Chips are links rather than buttons because
   * every one of them only changes the query string: a link is shareable,
   * middle-clickable, and works before React has hydrated — a button that
   * pushes the same URL does none of those.
   */
  hrefFor: (username: string) => string;
  /** Chips that would drop below the minimum render inert rather than 404. */
  isLocked?: (username: string) => boolean;
  children?: React.ReactNode;
}

/**
 * Shell furniture rather than a panel: who the tab is about, and any control
 * that recomputes every panel on it. Sits under the tab row so it is visible
 * from every panel without scrolling back up.
 */
export default function SelectionBar({
  label = 'PROFILES',
  profiles,
  selected,
  hrefFor,
  isLocked,
  children,
}: SelectionBarProps) {
  const chosen = new Set(selected.map((name) => name.toLowerCase()));

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-term-rule bg-term-bg2 px-[14px] py-[7px]">
      <span className="text-t9 tracking-tab text-term-muted2">{label}</span>
      <div className="flex flex-wrap items-center gap-1">
        {profiles.map((username) => {
          const active = chosen.has(username.toLowerCase());
          const locked = isLocked?.(username) ?? false;
          if (locked) {
            return (
              <span
                key={username}
                className={`${CHIP_BASE} cursor-not-allowed`}
                title="At least this many profiles are needed here"
                style={chipStyle(active)}
              >
                @{username}
              </span>
            );
          }
          return (
            <Link
              key={username}
              href={hrefFor(username)}
              scroll={false}
              aria-current={active ? 'true' : undefined}
              className={CHIP_BASE}
              style={chipStyle(active)}
            >
              @{username}
            </Link>
          );
        })}
      </div>
      {children ? (
        <div className="ml-auto flex min-w-0 flex-wrap items-center justify-end gap-3">
          {children}
        </div>
      ) : null}
    </div>
  );
}

export interface ClosenessPickerProps {
  value: number;
  hrefFor: (gapDays: number) => string;
}

/**
 * Was "gap days: 0 / 1 / 3". The tiers are the same; the words are what
 * somebody would actually say out loud.
 */
export const CLOSENESS_TIERS: Array<{ label: string; gapDays: number }> = [
  { label: 'SAME DAY', gapDays: 0 },
  { label: 'WITHIN A DAY', gapDays: 1 },
  { label: 'WITHIN THREE', gapDays: 3 },
  { label: 'WITHIN A WEEK', gapDays: 7 },
];

export function ClosenessPicker({ value, hrefFor }: ClosenessPickerProps) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-t9 tracking-tab text-term-muted2">HOW CLOSE</span>
      <div className="flex items-center gap-1">
        {CLOSENESS_TIERS.map((tier) => (
          <Link
            key={tier.gapDays}
            href={hrefFor(tier.gapDays)}
            scroll={false}
            aria-current={tier.gapDays === value ? 'true' : undefined}
            className={CHIP_BASE}
            style={chipStyle(tier.gapDays === value)}
          >
            {tier.label}
          </Link>
        ))}
      </div>
    </div>
  );
}
