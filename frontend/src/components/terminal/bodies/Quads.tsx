'use client';

import React from 'react';

export interface QuadDatum {
  tag: string;
  n: React.ReactNode;
  pct?: string;
  note?: string;
  tone?: string;
}

/** A 2×2 grid for four mutually exclusive buckets that together make a whole. */
export default function Quads({ items }: { items: QuadDatum[] }) {
  return (
    <div className="grid grid-cols-2">
      {items.map((item, index) => (
        <div
          key={`${item.tag}-${index}`}
          className="min-w-0 border-b border-r border-term-rule2 px-[10px] py-[9px]"
        >
          <p className="m-0 text-t95 tracking-crumb" style={{ color: item.tone ?? 'var(--accent)' }}>
            {item.tag}
          </p>
          <p className="terminal-num m-0 mt-[3px] text-t19 font-bold text-term-ink">
            {item.n}
            {item.pct ? (
              <span className="ml-[5px] text-t10 font-normal text-term-muted">{item.pct}</span>
            ) : null}
          </p>
          {item.note ? (
            <p className="m-0 mt-[3px] font-term-sans text-t10 text-term-dim">{item.note}</p>
          ) : null}
        </div>
      ))}
    </div>
  );
}
