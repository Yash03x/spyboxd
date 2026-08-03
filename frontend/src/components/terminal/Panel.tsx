'use client';

import React from 'react';

export interface PanelStat {
  /** The big number. Pre-formatted -- the panel does not format. */
  big: React.ReactNode;
  unit: string;
  /** CSS colour, defaults to --ink. Use --accent/--ok/--bad to grade it. */
  tone?: string;
}

export interface PanelProps {
  title: string;
  /** The `SRC` line: the table and column this panel reads. */
  src?: string;
  /** One or two sentences of plain-English context, in the sans face. */
  blurb?: string;
  stats?: PanelStat[];
  /**
   * The honest line at the bottom. Not decoration: where a panel cannot answer
   * fully it says so here. Prefer a value computed from real coverage over a
   * hardcoded sentence.
   */
  caveat?: React.ReactNode;
  /** Launch affordance for the twelve new signals: amber border and a badge. */
  isNew?: boolean;
  /** Take the full width of the panel grid. */
  wide?: boolean;
  children?: React.ReactNode;
}

/**
 * The panel shell every one of the 106 panels is built from: header with a
 * source line, optional blurb, optional big-number row, a body slot, and an
 * optional caveat. Border is 1px, background is flat, and there is no radius
 * and no shadow anywhere.
 */
export default function Panel({
  title,
  src,
  blurb,
  stats,
  caveat,
  isNew = false,
  wide = false,
  children,
}: PanelProps) {
  return (
    <section
      className={`border bg-term-panel ${isNew ? 'border-term-accent' : 'border-term-rule'} ${
        wide ? 'col-span-full' : ''
      }`}
      style={wide ? { gridColumn: '1 / -1' } : undefined}
    >
      <header
        className="flex items-center justify-between gap-[10px] border-b border-term-rule px-[10px] py-[7px]"
        style={{
          background: isNew
            ? 'color-mix(in srgb, var(--accent) 12%, var(--panelhd))'
            : 'var(--panelhd)',
        }}
      >
        <span className="flex min-w-0 items-center gap-[6px] text-t10 font-bold uppercase tracking-title text-term-accent">
          <span className="truncate">▸ {title}</span>
          {isNew ? (
            <span className="shrink-0 rounded-[2px] bg-term-accent px-1 py-px text-term-onaccent">
              NEW
            </span>
          ) : null}
        </span>
        {src ? (
          <span className="min-w-0 max-w-[46%] shrink truncate text-t9 text-term-dim">{src}</span>
        ) : null}
      </header>

      {blurb ? (
        <p className="m-0 border-b border-term-rule2 px-[10px] py-[7px] font-term-sans text-t105 text-term-ink3">
          {blurb}
        </p>
      ) : null}

      {stats && stats.length > 0 ? (
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-2 border-b border-term-rule2 px-[10px] py-[9px]">
          {stats.map((stat, index) => (
            <span key={index} className="flex items-baseline gap-[6px]">
              <span
                className="terminal-num text-t21 font-bold"
                style={{ color: stat.tone ?? 'var(--ink)' }}
              >
                {stat.big}
              </span>
              <span className="text-t95 uppercase tracking-tab text-term-muted">{stat.unit}</span>
            </span>
          ))}
        </div>
      ) : null}

      {children}

      {caveat ? (
        <p className="m-0 px-[10px] py-[6px] font-term-sans text-t10 text-term-dim">{caveat}</p>
      ) : null}
    </section>
  );
}
