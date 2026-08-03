'use client';

import React from 'react';

export interface DivergeDatum {
  name: string;
  /** Signed. Negative draws left of the centre line, positive right. */
  value: number;
  /** Sample size behind the value. */
  n?: number | string;
  /** Pre-formatted display of `value`. Defaults to a signed two-decimal figure. */
  display?: string;
}

export interface DivergeProps {
  items: DivergeDatum[];
  /** Column header for the left-hand label, e.g. 'GENRE' or 'DECADE'. */
  label: string;
  /** Axis legend, e.g. 'HARSHER ← → KINDER'. */
  axis: string;
  /** Largest absolute value the axis should represent. */
  max?: number;
}

const GRID = '64px minmax(0,1fr) 62px 42px';

function signed(value: number): string {
  const rounded = Math.abs(value).toFixed(2);
  if (value > 0) return `+${rounded}`;
  if (value < 0) return `−${rounded}`;
  return '0.00';
}

/**
 * Centre-line bars for signed values. A single averaged number hides exactly
 * what this body kind exists to show -- somebody can be harsh on comedy and
 * generous with documentary, and the mean of those two is nothing at all.
 */
export default function Diverge({ items, label, axis, max }: DivergeProps) {
  const ceiling = max ?? Math.max(...items.map((item) => Math.abs(item.value)), 0.01);

  return (
    <div>
      <div
        className="grid gap-[9px] border-b border-term-rule2 px-[10px] py-[5px] text-t9 tracking-tab text-term-muted2"
        style={{ gridTemplateColumns: GRID }}
      >
        <span>{label}</span>
        <span>{axis}</span>
        <span className="text-right">GAP</span>
        <span className="text-right">N</span>
      </div>

      {items.map((item, index) => {
        // Half the track is one side of the axis, so a value at the ceiling
        // fills 50% and negatives are offset left by their own width.
        const width = (Math.abs(item.value) / ceiling) * 50;
        const tone = item.value < 0 ? 'var(--bad)' : item.value > 0 ? 'var(--ok)' : 'var(--muted)';

        return (
          <div
            key={`${item.name}-${index}`}
            className="grid items-center gap-[9px] border-b border-term-rule2 px-[10px] py-[5px] hover:bg-term-panelhd"
            style={{ gridTemplateColumns: GRID }}
          >
            <span className="terminal-num truncate text-t11 text-term-ink2">{item.name}</span>
            <span className="relative block h-[9px] bg-term-track">
              <span className="absolute -top-[2px] -bottom-[2px] left-1/2 w-px bg-term-rule3" />
              <span
                className="absolute inset-y-0"
                style={{
                  left: item.value < 0 ? `${50 - width}%` : '50%',
                  width: `${Math.max(width, 0.5)}%`,
                  background: tone,
                }}
              />
            </span>
            <span className="terminal-num text-right text-t11" style={{ color: tone }}>
              {item.display ?? signed(item.value)}
            </span>
            <span className="terminal-num text-right text-t10 text-term-muted">{item.n ?? ''}</span>
          </div>
        );
      })}
    </div>
  );
}
