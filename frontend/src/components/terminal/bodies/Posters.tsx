'use client';

import Image from 'next/image';
import React from 'react';

export interface PosterDatum {
  title: string;
  sub?: React.ReactNode;
  /** Primary right-hand value. */
  right?: React.ReactNode;
  /** Caption under the value. */
  rightCaption?: React.ReactNode;
  /** CSS colour for the value. Defaults to --ink. */
  tone?: string;
  posterUrl?: string | null;
  href?: string;
}

/**
 * The 34×44 slot is drawn as a striped placeholder when a film has no poster.
 * Films with no poster are the subject of Films › Gaps, so hiding the row
 * would hide the very thing that tab is about.
 *
 * A URL that 404s falls back to the same placeholder rather than painting a
 * broken image: a stale poster path is our problem to absorb, not something to
 * show the reader as a torn icon.
 */
function PosterSlot({ url, alt }: { url?: string | null; alt: string }) {
  const [failed, setFailed] = React.useState(false);
  React.useEffect(() => setFailed(false), [url]);

  if (url && !failed) {
    return (
      <Image
        src={url}
        alt={alt}
        width={34}
        height={44}
        className="h-[44px] w-[34px] object-cover"
        unoptimized
        onError={() => setFailed(true)}
      />
    );
  }
  return (
    <span
      className="block h-[44px] w-[34px]"
      style={{
        background:
          'linear-gradient(135deg, var(--poster1) 0 4px, var(--poster2) 4px 8px)',
      }}
    />
  );
}

export default function Posters({ items }: { items: PosterDatum[] }) {
  return (
    <div>
      {items.map((item, index) => (
        <div
          key={`${item.title}-${index}`}
          className="grid items-center gap-[9px] border-b border-term-rule2 px-[10px] py-[5px] hover:bg-term-panelhd"
          style={{ gridTemplateColumns: '34px minmax(0,1fr) auto' }}
        >
          <PosterSlot url={item.posterUrl} alt={item.title} />
          <span className="min-w-0">
            <span className="block truncate font-term-sans text-t115 text-term-ink">
              {item.href ? (
                <a href={item.href} target="_blank" rel="noreferrer">
                  {item.title}
                </a>
              ) : (
                item.title
              )}
            </span>
            {item.sub !== undefined ? (
              <span className="mt-[2px] block truncate text-t10 text-term-muted">{item.sub}</span>
            ) : null}
          </span>
          <span className="text-right">
            {item.right !== undefined ? (
              <span
                className="terminal-num block text-t11"
                style={{ color: item.tone ?? 'var(--ink)' }}
              >
                {item.right}
              </span>
            ) : null}
            {item.rightCaption !== undefined ? (
              <span className="mt-[2px] block text-t95 text-term-dim">{item.rightCaption}</span>
            ) : null}
          </span>
        </div>
      ))}
    </div>
  );
}
