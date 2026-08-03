'use client';

import React from 'react';

export interface BarDatum {
  name: string;
  /** Drives the fill width. Compared against `max`. */
  weight: number;
  /** Rendered right of the track, pre-formatted. */
  value: React.ReactNode;
  /** Secondary figure, right-most column. */
  sub?: React.ReactNode;
  /** CSS colour for the fill. Defaults to --accent. */
  tone?: string;
}

export interface BarsProps {
  items: BarDatum[];
  /** Scale ceiling. Defaults to the largest weight present. */
  max?: number;
}

/**
 * The single most common body kind. A fixed three-column grid keeps the
 * tracks aligned across panels, which is what makes a wall of them readable.
 */
export default function Bars({ items, max }: BarsProps) {
  // Floored against a non-positive ceiling only. Flooring at 1 crushed every
  // panel whose weights are shares: a 4.1% keyword drew 4% of the track
  // instead of filling it as the largest value present.
  const largest = Math.max(...items.map((item) => item.weight), 0);
  const ceiling = max ?? (largest > 0 ? largest : 1);

  return (
    <div>
      {items.map((item, index) => (
        <div
          key={`${item.name}-${index}`}
          className="grid items-center gap-[9px] border-b border-term-rule2 px-[10px] py-[4.5px] hover:bg-term-panelhd"
          style={{ gridTemplateColumns: 'minmax(96px,1.4fr) minmax(60px,2fr) auto' }}
        >
          <span className="min-w-0 truncate font-term-sans text-t11 text-term-ink2">{item.name}</span>
          <span className="relative block h-[7px] overflow-hidden bg-term-track">
            <span
              className="absolute inset-y-0 left-0"
              style={{
                // A 2% floor keeps a real-but-tiny value visible; zero rows
                // still read as zero because the number beside them says so.
                width: `${Math.max(2, Math.round((item.weight / ceiling) * 100))}%`,
                background: item.tone ?? 'var(--accent)',
              }}
            />
          </span>
          <span className="flex items-baseline justify-end gap-2">
            <span className="terminal-num text-t11 text-term-ink">{item.value}</span>
            {item.sub !== undefined ? (
              <span className="terminal-num min-w-[32px] text-right text-t10 text-term-muted">
                {item.sub}
              </span>
            ) : null}
          </span>
        </div>
      ))}
    </div>
  );
}
