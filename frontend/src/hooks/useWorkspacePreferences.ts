'use client';

import { useAuth } from '@clerk/nextjs';
import { useCallback, useSyncExternalStore } from 'react';
import { EMPTY_WORKSPACE, normalizeWorkspace, type WorkspacePreferences } from '../lib/workspacePreferences';

const CHANGE = 'spyboxd-workspace-changed';
const cache = new Map<string, { raw: string | null; value: WorkspacePreferences }>();
function read(key: string | null): WorkspacePreferences {
  if (!key || typeof window === 'undefined') return EMPTY_WORKSPACE;
  try {
    const raw = window.localStorage.getItem(key);
    const previous = cache.get(key);
    if (previous?.raw === raw) return previous.value;
    const value = raw ? normalizeWorkspace(JSON.parse(raw)) : EMPTY_WORKSPACE;
    cache.set(key, { raw, value });
    return value;
  } catch { return EMPTY_WORKSPACE; }
}
function subscribe(notify: () => void) {
  window.addEventListener('storage', notify);
  window.addEventListener(CHANGE, notify);
  return () => { window.removeEventListener('storage', notify); window.removeEventListener(CHANGE, notify); };
}
const serverSnapshot = () => EMPTY_WORKSPACE;

export function useWorkspacePreferences() {
  const { userId, isLoaded } = useAuth();
  const key = isLoaded && userId ? `spyboxd.workspace.v1:${userId}` : null;
  const snapshot = useCallback(() => read(key), [key]);
  const preferences = useSyncExternalStore(subscribe, snapshot, serverSnapshot);
  const save = useCallback((change: (current: WorkspacePreferences) => WorkspacePreferences) => {
    if (!key) return false;
    try {
      window.localStorage.setItem(key, JSON.stringify(normalizeWorkspace(change(read(key)))));
      window.dispatchEvent(new Event(CHANGE));
      return true;
    } catch { return false; }
  }, [key]);
  return { preferences, save, ready: Boolean(key) };
}
