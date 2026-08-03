'use client';

import React from 'react';

/** Amber saturation scaled by value, floored at a visible zero cell. */
export function heatBackground(value: number, max: number): string {
  if (value <= 0) return 'var(--heat0)';
  const share = Math.round(16 + (value / Math.max(max, 1)) * 74);
  return `color-mix(in srgb, var(--accent) ${share}%, var(--heat0))`;
}

export interface CoWatchMatrixProps {
  labels: string[];
  /** Films both have seen. Drawn above the diagonal. */
  overlaps: number[][];
  /** Mean star distance on those same films. Drawn below the diagonal. */
  gaps: (number | null)[][];
  cellHeight?: string;
  minWidth?: string;
}

/**
 * One grid, two questions. People ask "how much do we overlap" and "do we
 * agree" about the same pair, so the design puts both in a single square
 * rather than two panels the reader has to hold in their head at once.
 */
export function CoWatchMatrix({
  labels,
  overlaps,
  gaps,
  cellHeight = '26px',
  minWidth = '540px',
}: CoWatchMatrixProps) {
  const maxOverlap = Math.max(1, ...overlaps.flat());
  const maxGap = Math.max(0.01, ...gaps.flat().map((value) => value ?? 0));
  const columns = `repeat(${labels.length + 1},minmax(64px,1fr))`;

  const cells: Array<{ key: string; value: string; background: string; color: string; size: string }> =
    [{ key: 'corner', value: '', background: 'transparent', color: 'var(--muted)', size: '9px' }];

  labels.forEach((label) => {
    cells.push({
      key: `head-${label}`,
      value: label,
      background: 'transparent',
      color: 'var(--muted)',
      size: '9px',
    });
  });

  labels.forEach((rowLabel, i) => {
    cells.push({
      key: `row-${rowLabel}`,
      value: rowLabel,
      background: 'transparent',
      color: 'var(--muted)',
      size: '9px',
    });
    labels.forEach((_, j) => {
      if (i === j) {
        cells.push({
          key: `${i}-${j}`,
          value: '·',
          background: 'var(--dim3)',
          color: 'var(--dim2)',
          size: '10px',
        });
        return;
      }
      if (j > i) {
        const value = overlaps[i]?.[j] ?? 0;
        cells.push({
          key: `${i}-${j}`,
          value: value ? value.toLocaleString() : '—',
          background: heatBackground(value, maxOverlap),
          color: 'var(--ink)',
          size: '10.5px',
        });
      } else {
        const value = gaps[i]?.[j];
        cells.push({
          key: `${i}-${j}`,
          value: value === null || value === undefined ? '—' : value.toFixed(2),
          background: 'transparent',
          // A wide star gap is the bad end of this scale, so it is graded
          // against the widest gap present rather than shown as neutral.
          color:
            value === null || value === undefined
              ? 'var(--dim)'
              : value <= 0.5
                ? 'var(--ok)'
                : value >= maxGap * 0.85
                  ? 'var(--bad)'
                  : 'var(--ink3)',
          size: '10.5px',
        });
      }
    });
  });

  return (
    <div className="overflow-x-auto">
      <div style={{ minWidth }} className="px-[10px] py-[9px]">
        <div className="grid gap-[2px]" style={{ gridTemplateColumns: columns }}>
          {cells.map((item) => (
            <span
              key={item.key}
              className="terminal-num grid place-items-center"
              style={{
                height: cellHeight,
                background: item.background,
                color: item.color,
                fontSize: item.size,
              }}
            >
              {item.value}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

export interface CalendarHeatProps {
  /** Column headings, Monday first. */
  days?: string[];
  /** One array of seven counts per week, oldest week first. */
  weeks: number[][];
  cellHeight?: string;
  minWidth?: string;
  /** Optional per-cell title text, same shape as `weeks`. */
  titles?: string[][];
}

/** Seven columns, one square per day, darker where more overlaps landed. */
export function CalendarHeat({
  days = ['M', 'T', 'W', 'T', 'F', 'S', 'S'],
  weeks,
  cellHeight = '17px',
  minWidth = '360px',
  titles,
}: CalendarHeatProps) {
  const max = Math.max(1, ...weeks.flat());

  return (
    <div className="overflow-x-auto">
      {/* Capped rather than stretched: this panel is full width so the grid
          would otherwise draw 200px-wide "days", and a heat map reads as a
          calendar only while its cells stay roughly square. */}
      <div style={{ minWidth, maxWidth: 720 }} className="px-[10px] py-[9px]">
        <div className="grid gap-[2px]" style={{ gridTemplateColumns: 'repeat(7,minmax(30px,1fr))' }}>
          {days.map((day, index) => (
            <span
              key={`day-${index}`}
              className="grid place-items-center text-t9 text-term-muted2"
              style={{ height: cellHeight }}
            >
              {day}
            </span>
          ))}
          {weeks.flatMap((week, weekIndex) =>
            week.map((value, dayIndex) => (
              <span
                key={`${weekIndex}-${dayIndex}`}
                className="terminal-num grid place-items-center text-t9"
                title={titles?.[weekIndex]?.[dayIndex]}
                style={{
                  height: cellHeight,
                  background: heatBackground(value, max),
                  color: value > 0 ? 'var(--ink)' : 'transparent',
                }}
              >
                {value > 0 ? value : ''}
              </span>
            )),
          )}
        </div>
      </div>
    </div>
  );
}
