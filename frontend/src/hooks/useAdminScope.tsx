'use client';

import React, { createContext, useCallback, useContext, useMemo, useState } from 'react';

import { useCurrentUser } from './useCurrentUser';

export type AdminScope = 'tracked' | 'global';

const SCOPE_STORAGE_KEY = 'spyboxd.admin-scope';

interface AdminScopeContextValue {
  isAdmin: boolean;
  userReady: boolean;
  scope: AdminScope;
  isGlobalAdminView: boolean;
  effectiveScope: AdminScope;
  setScope: (scope: AdminScope) => void;
}

const AdminScopeContext = createContext<AdminScopeContextValue | null>(null);

function readStoredScope(): AdminScope {
  if (typeof window === 'undefined') return 'global';
  try {
    return window.localStorage.getItem(SCOPE_STORAGE_KEY) === 'tracked' ? 'tracked' : 'global';
  } catch {
    // Storage can be denied even when `window.localStorage` exists. Scope is a
    // convenience, so a browser privacy setting must not take down the app.
    return 'global';
  }
}

export function AdminScopeProvider({ children }: { children: React.ReactNode }) {
  const currentUserQuery = useCurrentUser();
  const [scope, setScopeState] = useState<AdminScope>(readStoredScope);

  const setScope = useCallback((next: AdminScope) => {
    setScopeState(next);
    try {
      window.localStorage.setItem(SCOPE_STORAGE_KEY, next);
    } catch {
      // Storage can be unavailable (private browsing); in-memory state still applies.
    }
  }, []);

  const isAdmin = currentUserQuery.data?.is_admin ?? false;
  const isGlobalAdminView = isAdmin && scope === 'global';
  const value = useMemo<AdminScopeContextValue>(() => ({
    isAdmin,
    userReady: currentUserQuery.isSuccess || currentUserQuery.isError,
    scope,
    isGlobalAdminView,
    effectiveScope: isGlobalAdminView ? 'global' : 'tracked',
    setScope,
  }), [currentUserQuery.isError, currentUserQuery.isSuccess, isAdmin, isGlobalAdminView, scope, setScope]);

  return <AdminScopeContext.Provider value={value}>{children}</AdminScopeContext.Provider>;
}

export function useAdminScope(): AdminScopeContextValue {
  const value = useContext(AdminScopeContext);
  if (!value) throw new Error('useAdminScope must be used within an AdminScopeProvider');
  return value;
}
