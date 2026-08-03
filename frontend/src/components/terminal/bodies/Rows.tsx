'use client';

import Link from 'next/link';
import React from 'react';

export type CellAlign = 'left' | 'right' | 'center';

export interface Cell {
  text: React.ReactNode;
  align?: CellAlign;
  /** A value from the dense scale, e.g. '10px'. Defaults to 11px. */
  size?: string;
  /** CSS colour. Defaults to --ink2. */
  tone?: string;
  /** 's' switches the cell to IBM Plex Sans -- prose, film titles, names. */
  font?: 's' | 'm';
  /** Let the cell wrap instead of truncating. */
  wrap?: boolean;
}

export interface RowDef {
  cells: Cell[];
  /** Makes the whole row a link. Used by Overview's cross-panel deep links. */
  href?: string;
}

export interface RowsProps {
  /** CSS grid-template-columns for both the head and every row. */
  columns: string;
  head?: Array<string | [string, CellAlign]>;
  rows: RowDef[];
}

export function cell(text: React.ReactNode, options: Omit<Cell, 'text'> = {}): Cell {
  return { text, ...options };
}

function cellStyle(item: Cell): React.CSSProperties {
  return {
    textAlign: item.align ?? 'left',
    fontSize: item.size ?? '11px',
    lineHeight: '15px',
    color: item.tone ?? 'var(--ink2)',
    fontFamily: item.font === 's' ? 'var(--font-sans)' : 'var(--font-mono)',
    whiteSpace: item.wrap ? 'normal' : 'nowrap',
  };
}

/**
 * The generic table. Each panel supplies its own column template, so this
 * component never guesses at widths -- density comes from the caller knowing
 * exactly how wide its own numbers are.
 */
export default function Rows({ columns, head, rows }: RowsProps) {
  return (
    <div>
      {head ? (
        <div
          className="grid gap-[9px] border-b border-term-rule2 px-[10px] py-[5px] text-t9 tracking-tab text-term-muted2"
          style={{ gridTemplateColumns: columns }}
        >
          {head.map((entry, index) => {
            const [label, align] = Array.isArray(entry) ? entry : [entry, 'left' as CellAlign];
            return (
              <span key={index} className="truncate" style={{ textAlign: align }}>
                {label}
              </span>
            );
          })}
        </div>
      ) : null}

      {rows.map((row, rowIndex) => {
        const body = row.cells.map((item, cellIndex) => (
          <span
            key={cellIndex}
            className="terminal-num min-w-0 overflow-hidden text-ellipsis"
            style={cellStyle(item)}
          >
            {item.text}
          </span>
        ));

        const rowClass =
          'grid items-baseline gap-[9px] border-b border-term-rule2 px-[10px] py-[5.5px] hover:bg-term-panelhd';

        return row.href ? (
          <Link
            key={rowIndex}
            href={row.href}
            className={`${rowClass} no-underline hover:no-underline`}
            style={{ gridTemplateColumns: columns }}
          >
            {body}
          </Link>
        ) : (
          <div key={rowIndex} className={rowClass} style={{ gridTemplateColumns: columns }}>
            {body}
          </div>
        );
      })}
    </div>
  );
}
