'use client';

import React from 'react';

export interface SelectionBarProps {
  profiles: string[];
  selected: string[];
  onToggle: (username: string) => void;
  minSelection?: number;
  /** Extra controls rendered to the right, e.g. the closeness selector. */
  children?: React.ReactNode;
}

/**
 * Shell furniture rather than a panel: who the tab is about, and any control
 * that recomputes every panel on it. Sits under the tab row so it is visible
 * from every panel without scrolling back up.
 */
export default function SelectionBar({
  profiles,
  selected,
  onToggle,
  minSelection = 2,
  children,
}: SelectionBarProps) {
  const chosen = new Set(selected.map((name) => name.toLowerCase()));

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-term-rule bg-term-bg2 px-[14px] py-[7px]">
      <span className="text-t9 tracking-tab text-term-muted2">PROFILES</span>
      <div className="flex flex-wrap items-center gap-1">
        {profiles.map((username) => {
          const active = chosen.has(username.toLowerCase());
          // Dropping below the minimum would leave the tab with nothing to
          // compare, so the last selected chip refuses rather than emptying.
          const locked = active && selected.length <= minSelection;
          return (
            <button
              key={username}
              type="button"
              onClick={() => !locked && onToggle(username)}
              disabled={locked}
              title={locked ? `At least ${minSelection} profiles are needed here` : undefined}
              className="rounded-[3px] border px-2 py-[3px] text-t10 disabled:cursor-not-allowed"
              style={{
                borderColor: active ? 'var(--accent)' : 'var(--rule)',
                background: active ? 'color-mix(in srgb, var(--accent) 14%, transparent)' : 'transparent',
                color: active ? 'var(--accent)' : 'var(--muted)',
              }}
            >
              @{username}
            </button>
          );
        })}
      </div>
      {children ? <div className="ml-auto flex items-center gap-3">{children}</div> : null}
    </div>
  );
}

export interface ClosenessPickerProps {
  value: number;
  onChange: (gapDays: number) => void;
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

export function ClosenessPicker({ value, onChange }: ClosenessPickerProps) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-t9 tracking-tab text-term-muted2">HOW CLOSE</span>
      <div className="flex items-center gap-1">
        {CLOSENESS_TIERS.map((tier) => {
          const active = tier.gapDays === value;
          return (
            <button
              key={tier.gapDays}
              type="button"
              onClick={() => onChange(tier.gapDays)}
              className="rounded-[3px] border px-2 py-[3px] text-t10"
              style={{
                borderColor: active ? 'var(--accent)' : 'var(--rule)',
                background: active ? 'color-mix(in srgb, var(--accent) 14%, transparent)' : 'transparent',
                color: active ? 'var(--accent)' : 'var(--muted)',
              }}
            >
              {tier.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
