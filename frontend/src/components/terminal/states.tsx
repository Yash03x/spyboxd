'use client';

import Link from 'next/link';
import React from 'react';
import { AlertOctagon, AlertTriangle, Clock, RefreshCw } from 'lucide-react';

/**
 * Skeletons match the panel's own row geometry rather than showing a spinner,
 * so the shape of what is coming is visible while it loads and nothing jumps
 * when it arrives.
 */
export function PanelSkeleton({ rows = 5, height = 15 }: { rows?: number; height?: number }) {
  return (
    <div>
      {Array.from({ length: rows }).map((_, index) => (
        <div
          key={index}
          className="flex items-center gap-[9px] border-b border-term-rule2 px-[10px] py-[5.5px]"
        >
          <span
            className="terminal-skeleton flex-1"
            style={{ height, opacity: 1 - index * 0.08 }}
          />
          <span className="terminal-skeleton w-12" style={{ height }} />
        </div>
      ))}
    </div>
  );
}

export function BarsSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div>
      {Array.from({ length: rows }).map((_, index) => (
        <div
          key={index}
          className="grid items-center gap-[9px] border-b border-term-rule2 px-[10px] py-[4.5px]"
          style={{ gridTemplateColumns: 'minmax(96px,1.4fr) minmax(60px,2fr) auto' }}
        >
          <span className="terminal-skeleton h-[11px]" />
          <span className="terminal-skeleton h-[7px]" style={{ width: `${90 - index * 11}%` }} />
          <span className="terminal-skeleton h-[11px] w-10" />
        </div>
      ))}
    </div>
  );
}

/**
 * An empty state says what is missing and what would fill it. "No data" on its
 * own reads as a bug; naming the missing surface turns it into an instruction.
 */
export function PanelEmpty({
  title,
  body,
  cta,
}: {
  title: string;
  body: string;
  cta?: { label: string; href: string };
}) {
  return (
    <div className="px-[10px] py-[14px]">
      {/* A real heading: an empty state is the only thing on the panel, and it
          is what a screen reader should announce when the panel is reached. */}
      <h3 className="m-0 font-term-sans text-t115 font-semibold text-term-ink">{title}</h3>
      <p className="m-0 mt-[5px] max-w-[42rem] font-term-sans text-t105 text-term-ink3">{body}</p>
      {cta ? (
        <Link
          href={cta.href}
          className="mt-[10px] inline-flex items-center gap-[6px] rounded-[3px] border border-term-rule px-[9px] py-1 text-t95 font-bold text-term-ink3 no-underline hover:border-term-accent hover:text-term-accent hover:no-underline"
        >
          {cta.label}
        </Link>
      ) : null}
    </div>
  );
}

export type ErrorSeverity = 'fatal' | 'degraded' | 'quiet';

const SEVERITY = {
  fatal: { label: 'FATAL', tone: 'var(--bad)', Icon: AlertOctagon },
  degraded: { label: 'DEGRADED', tone: 'var(--accent)', Icon: AlertTriangle },
  quiet: { label: 'QUIET', tone: 'var(--muted)', Icon: Clock },
} as const;

/**
 * Errors are graded so a failed panel does not take the tab down with it. The
 * API's own message is shown verbatim rather than swallowed into an empty
 * result, because "nothing matched" and "the request failed" are different
 * facts and the reader is entitled to know which one happened.
 */
export function PanelError({
  severity = 'degraded',
  title,
  body,
  detail,
  onRetry,
  actionLabel = 'TRY AGAIN',
}: {
  severity?: ErrorSeverity;
  title: string;
  body: string;
  detail?: string | null;
  onRetry?: () => void;
  actionLabel?: string;
}) {
  const { label, tone, Icon } = SEVERITY[severity];

  return (
    <div className="px-[10px] py-[13px]">
      <div className="flex items-baseline justify-between gap-2">
        <span className="inline-flex items-center gap-[6px] text-t95 font-bold tracking-tab" style={{ color: tone }}>
          <Icon size={12} aria-hidden />
          {label}
        </span>
      </div>
      <p className="m-0 mt-[6px] font-term-sans text-t115 font-semibold text-term-ink">{title}</p>
      <p className="m-0 mt-[6px] font-term-sans text-t10 text-term-muted2">{body}</p>
      {detail ? (
        <p className="m-0 mt-[6px] break-words font-term-sans text-t10 text-term-dim">{detail}</p>
      ) : null}
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="mt-[10px] inline-flex items-center gap-[6px] rounded-[3px] border border-term-rule bg-transparent px-[9px] py-1 text-t95 font-bold text-term-ink3 hover:border-term-accent hover:text-term-accent"
        >
          <RefreshCw size={11} aria-hidden />
          {actionLabel}
        </button>
      ) : null}
    </div>
  );
}

export interface PanelStateOptions {
  isLoading: boolean;
  error: unknown;
  isEmpty?: boolean;
  empty?: { title: string; body: string; cta?: { label: string; href: string } };
  severity?: ErrorSeverity;
  errorTitle?: string;
  errorBody?: string;
  onRetry?: () => void;
  skeleton?: React.ReactNode;
}

function errorDetail(error: unknown): string | null {
  if (!error) return null;
  if (typeof error === 'string') return error;
  if (error instanceof Error) return error.message;
  return null;
}

/**
 * One helper so every panel handles loading, empty and error the same way.
 * Returns `null` when the panel should render its own body.
 */
export function panelState(options: PanelStateOptions): React.ReactNode | null {
  if (options.isLoading) {
    return options.skeleton ?? <PanelSkeleton />;
  }
  if (options.error) {
    return (
      <PanelError
        severity={options.severity ?? 'degraded'}
        title={options.errorTitle ?? 'This panel could not be loaded'}
        body={
          options.errorBody ??
          'Every other panel on this tab is unaffected. The message from the API is below.'
        }
        detail={errorDetail(options.error)}
        onRetry={options.onRetry}
      />
    );
  }
  if (options.isEmpty) {
    return (
      <PanelEmpty
        title={options.empty?.title ?? 'Nothing to show yet'}
        body={
          options.empty?.body ??
          'No rows matched. Widen the selection or wait for the next refresh.'
        }
        cta={options.empty?.cta}
      />
    );
  }
  return null;
}
