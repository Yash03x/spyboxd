'use client';

import React from 'react';

export type EdgeKind = 'mutual' | 'follows' | 'followedBy' | 'untracked';

export interface EgoLeaf {
  username: string;
  kind: EdgeKind;
  /** False for accounts the group orbits that we hold no data for. */
  tracked: boolean;
}

export interface EgoGraphProps {
  centre: string;
  leaves: EgoLeaf[];
  /** Re-centre the graph on a leaf. */
  onSelect?: (username: string) => void;
}

const BOX_WIDTH = 620;
const BOX_HEIGHT = 470;
const CENTRE_X = 310;
const CENTRE_Y = 218;
const RING = 168;

function initials(username: string): string {
  return username.slice(0, 2).toUpperCase();
}

/**
 * The ego follow graph: one centred node, the rest on a ring. Solid green is
 * mutual, solid amber is one-way, dashed grey is somebody the group orbits
 * that we have never synced.
 *
 * Node rings carry a 4px panel-coloured halo so edges appear to terminate at
 * the circle rather than run underneath it.
 */
export default function EgoGraph({ centre, leaves, onSelect }: EgoGraphProps) {
  return (
    <>
      <div className="flex flex-wrap gap-x-[14px] gap-y-1 border-b border-term-rule2 px-[10px] py-[6px] text-t95 text-term-muted">
        <span className="inline-flex items-center gap-[5px]">
          <span className="h-[2px] w-4 bg-term-ok" />
          MUTUAL
        </span>
        <span className="inline-flex items-center gap-[5px]">
          <span className="h-[2px] w-4 bg-term-accent" />
          ONE WAY
        </span>
        <span className="inline-flex items-center gap-[5px]">
          <span
            className="h-[2px] w-4"
            style={{
              background:
                'repeating-linear-gradient(90deg, var(--muted2) 0 3px, transparent 3px 6px)',
            }}
          />
          NOT TRACKED
        </span>
      </div>

      <div className="flex justify-center overflow-x-auto p-[14px]">
        <div
          className="relative shrink-0"
          style={{ width: BOX_WIDTH, height: BOX_HEIGHT }}
          role="img"
          aria-label={`Follow graph centred on ${centre}, ${leaves.length} connections`}
        >
          {leaves.map((leaf, index) => {
            const angle = -Math.PI / 2 + (index * 2 * Math.PI) / Math.max(leaves.length, 1);
            const radius = leaf.tracked ? 25 : 21;
            const startRadius = 37;
            const endRadius = RING - radius - 6;
            const stroke =
              leaf.kind === 'mutual'
                ? 'var(--ok)'
                : leaf.tracked
                  ? 'var(--accent)'
                  : 'var(--dim)';

            return (
              <span
                key={`edge-${leaf.username}`}
                className="absolute h-0 origin-[0_0]"
                style={{
                  left: `${CENTRE_X + startRadius * Math.cos(angle)}px`,
                  top: `${CENTRE_Y + startRadius * Math.sin(angle)}px`,
                  width: `${endRadius - startRadius}px`,
                  transform: `rotate(${(angle * 180) / Math.PI}deg)`,
                  borderTop: leaf.tracked
                    ? `${leaf.kind === 'mutual' ? 2 : 1.6}px solid ${stroke}`
                    : '1.5px dashed var(--dim)',
                  opacity: leaf.tracked ? 0.9 : 0.55,
                }}
              />
            );
          })}

          <span
            className="absolute flex -translate-x-1/2 -translate-y-1/2 flex-col items-center gap-2"
            style={{ left: `${CENTRE_X}px`, top: `${CENTRE_Y}px` }}
          >
            <span
              className="grid h-[66px] w-[66px] place-items-center rounded-full text-[17px] font-bold"
              style={{
                background: 'color-mix(in srgb, var(--accent) 18%, transparent)',
                border: '2px solid var(--ink)',
                color: 'var(--accent2)',
                boxShadow: '0 0 0 4px var(--panel)',
              }}
            >
              {initials(centre)}
            </span>
            <span className="whitespace-nowrap text-t11 font-semibold text-term-ink">
              @{centre}
            </span>
          </span>

          {leaves.map((leaf, index) => {
            const angle = -Math.PI / 2 + (index * 2 * Math.PI) / Math.max(leaves.length, 1);
            const radius = leaf.tracked ? 25 : 21;
            const x = CENTRE_X + RING * Math.cos(angle);
            const y = CENTRE_Y + RING * Math.sin(angle);

            const node = (
              <>
                <span
                  className="grid place-items-center rounded-full font-bold"
                  style={{
                    width: radius * 2,
                    height: radius * 2,
                    fontSize: leaf.tracked ? '12px' : '11px',
                    color: leaf.tracked ? 'var(--accent2)' : 'var(--muted)',
                    background: leaf.tracked
                      ? 'color-mix(in srgb, var(--accent) 10%, transparent)'
                      : 'var(--track)',
                    border: leaf.tracked
                      ? `1.5px solid ${
                          leaf.kind === 'mutual'
                            ? 'var(--ok)'
                            : 'color-mix(in srgb, var(--accent) 55%, transparent)'
                        }`
                      : '1.25px dashed var(--dim2)',
                    boxShadow: '0 0 0 4px var(--panel)',
                  }}
                >
                  {initials(leaf.username)}
                </span>
                <span
                  className="whitespace-nowrap text-t11 font-semibold"
                  style={{ color: leaf.tracked ? 'var(--ink3)' : 'var(--dim)' }}
                >
                  @{leaf.username}
                </span>
              </>
            );

            const style: React.CSSProperties = { left: `${x}px`, top: `${y}px` };
            const className =
              'absolute flex -translate-x-1/2 -translate-y-1/2 flex-col items-center gap-2';

            // Only tracked counterparts can be re-centred -- there is nothing
            // to show for an account we hold no data for.
            return leaf.tracked && onSelect ? (
              <button
                key={`node-${leaf.username}`}
                type="button"
                onClick={() => onSelect(leaf.username)}
                className={`${className} cursor-pointer border-none bg-transparent p-0`}
                style={style}
              >
                {node}
              </button>
            ) : (
              <span key={`node-${leaf.username}`} className={className} style={style}>
                {node}
              </span>
            );
          })}
        </div>
      </div>
    </>
  );
}
