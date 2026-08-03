'use client';

import React from 'react';

export interface NoteDatum {
  label: React.ReactNode;
  text: React.ReactNode;
}

/**
 * Label plus paragraph. Used wherever the honest answer is prose rather than a
 * number -- why a pick fits, what an export unlocks, what we cannot see.
 */
export default function Notes({ items }: { items: NoteDatum[] }) {
  return (
    <div>
      {items.map((item, index) => (
        <div key={index} className="border-b border-term-rule2 px-[10px] py-[7px]">
          <p className="m-0 font-term-sans text-t11 font-semibold text-term-ink">{item.label}</p>
          <div className="m-0 mt-[3px] font-term-sans text-t105 text-term-ink3">{item.text}</div>
        </div>
      ))}
    </div>
  );
}
