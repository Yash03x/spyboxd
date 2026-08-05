'use client';

import Link from 'next/link';
import React from 'react';
import { SignOutButton, UserButton, useAuth } from '@clerk/nextjs';
import { useQuery } from '@tanstack/react-query';
import { LogOut } from 'lucide-react';
import { BUILD_REVISION, SHORT_BUILD_REVISION } from '../../buildRevision';
import { useCurrentUser } from '../../hooks/useCurrentUser';
import { useScopedProfiles } from '../../hooks/useScopedProfiles';
import { dashboardApi } from '../../services/api';
import { useAdminScope } from '../../hooks/useAdminScope';
import { ThemeToggle } from './theme';
import type { SectionDef, TabDef } from './sections';

const CHIP =
  'inline-flex items-center gap-[5px] rounded-[3px] border border-term-rule px-2 py-[3px] whitespace-nowrap';

/**
 * The admin data-scope lens, in terminal dress. It stays in the status bar
 * rather than moving to Data › Profiles with the request queue: scope changes
 * what every panel in the product is computed from, so it belongs beside the
 * counts it changes.
 */
function AdminScopeChips() {
  const { isAdmin, scope, setScope } = useAdminScope();
  if (!isAdmin) return null;

  const chip = (value: 'tracked' | 'global', label: string) => (
    <button
      key={value}
      type="button"
      aria-pressed={scope === value}
      onClick={() => setScope(value)}
      className="rounded-[3px] border px-2 py-[3px] text-t10"
      style={{
        borderColor: scope === value ? 'var(--accent)' : 'var(--rule)',
        background:
          scope === value ? 'color-mix(in srgb, var(--accent) 14%, transparent)' : 'transparent',
        color: scope === value ? 'var(--accent)' : 'var(--muted)',
      }}
    >
      {label}
    </button>
  );

  return (
    <div className="flex shrink-0 items-center gap-1" aria-label="Data scope">
      {chip('tracked', 'Monitored')}
      {chip('global', 'Global admin')}
    </div>
  );
}

/**
 * 34px, sticky, and the only permanently visible statement of where you are
 * and how much data is behind it.
 */
export default function StatusBar({ section, tab }: { section: SectionDef; tab: TabDef }) {
  const { isSignedIn } = useAuth();
  const { effectiveScope, userReady } = useAdminScope();
  const currentUser = useCurrentUser(Boolean(isSignedIn));
  const profiles = useScopedProfiles();

  const analytics = useQuery({
    queryKey: ['dashboard-analytics', effectiveScope],
    queryFn: () => dashboardApi.getAnalytics(effectiveScope),
    enabled: userReady && Boolean(isSignedIn),
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const profileCount = profiles.data?.length ?? null;
  const filmCount = analytics.data?.system_stats.total_movies_tracked ?? null;
  const account = currentUser.data?.letterboxd_username
    ? `@${currentUser.data.letterboxd_username}`
    : 'Account';

  const counts =
    profileCount !== null || filmCount !== null ? (
      <span className={`${CHIP} shrink-0`}>
        {profileCount !== null ? `${profileCount} PROFILES` : '—'}
        {filmCount !== null ? ` · ${filmCount.toLocaleString()} FILMS` : ''}
        <span className="text-term-dim">
          {effectiveScope === 'global' ? ' · MANAGED LIBRARY' : ' · MONITORED'}
        </span>
      </span>
    ) : null;

  return (
    // One row at desktop width. On a phone the bar wraps rather than
    // duplicating its contents into a second hidden copy: the crumb and the
    // account controls stay on the first line, and the chips that describe the
    // data flow onto the second.
    <div className="sticky top-0 z-50 flex min-h-[34px] flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-term-rule bg-term-bg2 px-3 py-1 text-t105 md:h-[34px] md:flex-nowrap md:py-0">
      <div className="order-1 flex min-w-0 flex-1 items-center gap-[10px] md:flex-none">
        <span className="hidden text-term-muted2 sm:inline">SPYBOXD /</span>
        <span className="whitespace-nowrap font-bold tracking-crumb text-term-accent">
          {section.ordinal} {section.name.toUpperCase()}
        </span>
        <span className="text-term-dim2">›</span>
        <span className="truncate text-term-ink3">{tab.label}</span>
      </div>

      <div className="order-3 flex w-full min-w-0 items-center gap-2 overflow-x-auto text-term-muted md:order-2 md:ml-auto md:w-auto">
        <AdminScopeChips />
        {counts}
      </div>

      <div className="order-2 flex shrink-0 items-center gap-2 text-term-muted md:order-3">
        {isSignedIn ? (
          <>
            <span className={`${CHIP} shrink-0`} title={account}>
              <UserButton />
              <span className="hidden max-w-[9rem] truncate sm:inline">{account}</span>
            </span>
            <SignOutButton redirectUrl="/">
              <button
                type="button"
                // Labelled rather than left to its icon: the caption is hidden
                // below `lg`, and an unlabelled icon button is unreachable by
                // name.
                aria-label="Sign out"
                className={`${CHIP} shrink-0 hover:border-term-accent hover:text-term-accent`}
                title="Sign out"
              >
                <LogOut size={11} aria-hidden />
                <span className="hidden lg:inline">SIGN OUT</span>
              </button>
            </SignOutButton>
          </>
        ) : (
          <Link href="/sign-in" className={`${CHIP} no-underline hover:border-term-accent hover:no-underline`}>
            SIGN IN
          </Link>
        )}

        <ThemeToggle />

        {/* Which build is actually running -- the web half of the API's
            /health revision. Hidden below lg: it is an operator's fact, not a
            reader's, and phone width is spent on the reader. */}
        <span
          className="hidden text-t9 text-term-dim2 lg:inline"
          title={`frontend build ${BUILD_REVISION}`}
          data-testid="build-revision"
        >
          {SHORT_BUILD_REVISION}
        </span>
      </div>
    </div>
  );
}
