'use client';

import React from 'react';

export interface SparkDatum {
  label: string;
  value: number;
  /**
   * Optional subset drawn from the bottom of the same bar -- e.g. first-time
   * watches inside total watches. The gap between the two is the story.
   */
  inner?: number;
  /** Pre-formatted display of `value`. */
  display?: string;
  /** Full sentence for the bar, exposed as its title and accessible name. */
  hint?: string;
  /** Draw the bar as provisional -- a month still in progress, say. */
  partial?: boolean;
}

export interface SparkProps {
  items: SparkDatum[];
  max?: number;
  /** Appended to each printed value, e.g. '%'. */
  suffix?: string;
  tone?: string;
}

/** A flat bar column: no gridlines, no legend, no axis labels. */
export default function Spark({ items, max, suffix = '', tone }: SparkProps) {
  const ceiling = max ?? Math.max(...items.map((item) => item.value), 1);

  return (
    <div className="flex h-[118px] items-end gap-1 px-[10px] pb-[5px] pt-[10px]">
      {items.map((item, index) => (
        <span
          key={`${item.label}-${index}`}
          className="flex h-full min-w-0 flex-1 flex-col items-center justify-end gap-[3px]"
          title={item.hint}
          aria-label={item.hint}
        >
          <span className="terminal-num text-t9 text-term-ink3">
            {item.display ?? (item.value === 0 ? '' : `${item.value}${suffix}`)}
          </span>
          <span
            className="relative w-full"
            style={{
              height: `${(item.value / ceiling) * 100}%`,
              background: tone ?? 'var(--accent)',
              // A month still in progress is drawn hatched rather than solid,
              // so a half-finished month cannot be misread as a collapse.
              opacity: item.partial ? 0.55 : 1,
            }}
          >
            {item.inner ? (
              <span
                className="absolute inset-x-0 bottom-0 bg-term-barmuted"
                style={{ height: `${Math.min(100, (item.inner / Math.max(item.value, 1)) * 100)}%` }}
              />
            ) : null}
          </span>
          <span className="text-t85 text-term-muted2">{item.label}</span>
        </span>
      ))}
    </div>
  );
}
