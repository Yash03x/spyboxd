'use client';

import { useCallback, useMemo } from 'react';
import { usePathname, useSearchParams } from 'next/navigation';

import { useScopedProfiles } from './useScopedProfiles';
import { useUrlProfileSelection } from './useUrlProfileSelection';

export interface TerminalSelectionOptions {
  minSelection?: number;
  maxSelection?: number;
  defaultCount?: number;
}

/**
 * The profile selection every comparison tab reads.
 *
 * Thin wrapper over the existing URL-backed hook. The redesign keeps selection
 * in the query string so a tab is linkable, and this adds the URL *builders*
 * the chips need. A chip that is a link works before React has hydrated, can be
 * middle-clicked, and can be copied out of the address bar — none of which a
 * button that pushes the same URL can do, and the first of those is why the
 * production build behaved differently from the dev server.
 */
export function useTerminalSelection(options: TerminalSelectionOptions = {}) {
  const minSelection = options.minSelection ?? 2;
  const profilesQuery = useScopedProfiles();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const available = useMemo(
    () => (profilesQuery.data ?? []).map((profile) => profile.username),
    [profilesQuery.data],
  );

  const selection = useUrlProfileSelection(available, {
    minSelection,
    maxSelection: options.maxSelection,
    defaultCount: options.defaultCount ?? Math.min(available.length, 6),
  });

  const selected = selection.appliedProfiles;

  /** Build a URL for an explicit selection, preserving every other param. */
  const urlFor = useCallback(
    (profiles: string[], extra: Record<string, string | null> = {}) => {
      const params = new URLSearchParams(searchParams.toString());
      params.delete('profiles');
      profiles.forEach((profile) => params.append('profiles', profile));
      Object.entries(extra).forEach(([key, value]) => {
        if (value === null) params.delete(key);
        else params.set(key, value);
      });
      const query = params.toString();
      return query ? `${pathname}?${query}` : pathname;
    },
    [pathname, searchParams],
  );

  /** Where a toggle chip goes: adds the profile, or removes it if already in. */
  const toggleHref = useCallback(
    (username: string) => {
      const next = selected.includes(username)
        ? selected.filter((name) => name !== username)
        : [...selected, username];
      // Dropping below the minimum would leave the tab with nothing to
      // compare, so that chip links back to the selection it already has.
      return urlFor(next.length >= minSelection ? next : selected);
    },
    [minSelection, selected, urlFor],
  );

  /** Where a pair chip goes: keeps the first slot and swaps the second. */
  const pairHref = useCallback(
    (username: string) => {
      if (selected[0] === username) return urlFor(selected.slice(0, 2));
      return urlFor([selected[0] ?? username, username]);
    },
    [selected, urlFor],
  );

  /** Any other single query parameter, with the selection carried through. */
  const paramHref = useCallback(
    (key: string, value: string) => urlFor(selected, { [key]: value }),
    [selected, urlFor],
  );

  const isLockedByMinimum = useCallback(
    (username: string) => selected.includes(username) && selected.length <= minSelection,
    [minSelection, selected],
  );

  return {
    available,
    selected,
    isInitialized: selection.isInitialized,
    isLoading: profilesQuery.isLoading,
    error: profilesQuery.error,
    minSelection,
    urlFor,
    toggleHref,
    pairHref,
    paramHref,
    isLockedByMinimum,
  };
}
