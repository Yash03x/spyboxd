'use client';

import { useCallback, useMemo } from 'react';

import { useScopedProfiles } from './useScopedProfiles';
import { useUrlProfileSelection } from './useUrlProfileSelection';

export interface TerminalSelectionOptions {
  minSelection?: number;
  maxSelection?: number;
  defaultCount?: number;
}

/**
 * The profile selection every comparison tab reads. Thin wrapper over the
 * existing URL-backed hook: the redesign keeps selection in the query string
 * so a tab is linkable, and adds a single-toggle helper because the terminal
 * shell selects with chips rather than a multi-select dialog.
 */
export function useTerminalSelection(options: TerminalSelectionOptions = {}) {
  const minSelection = options.minSelection ?? 2;
  const profilesQuery = useScopedProfiles();

  const available = useMemo(
    () => (profilesQuery.data ?? []).map((profile) => profile.username),
    [profilesQuery.data],
  );

  const selection = useUrlProfileSelection(available, {
    minSelection,
    maxSelection: options.maxSelection,
    defaultCount: options.defaultCount ?? Math.min(available.length, 6),
  });

  const toggle = useCallback(
    (username: string) => {
      const current = selection.appliedProfiles;
      const next = current.includes(username)
        ? current.filter((name) => name !== username)
        : [...current, username];
      // applyProfiles refuses anything under the minimum, so a toggle that
      // would empty the comparison is a no-op rather than a broken tab.
      selection.applyProfiles(next);
    },
    [selection],
  );

  return {
    available,
    selected: selection.appliedProfiles,
    toggle,
    isInitialized: selection.isInitialized,
    isLoading: profilesQuery.isLoading,
    error: profilesQuery.error,
    replaceParams: selection.replaceParams,
    minSelection,
  };
}
