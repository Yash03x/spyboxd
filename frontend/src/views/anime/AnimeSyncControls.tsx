'use client';

import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { getAnimeSync, setAnimeSync, syncAnime } from '../../services/animeApi';

const BUTTON = 'min-h-10 rounded border border-term-rule px-3 py-2 text-t11 text-term-accent disabled:opacity-50';
export default function AnimeSyncControls({ ownerId, hasSnapshot }: { ownerId: string | null | undefined; hasSnapshot: boolean }) {
  const client = useQueryClient();
  const key = ['personal-anime-sync', ownerId];
  const query = useQuery({ queryKey: key, queryFn: getAnimeSync, enabled: Boolean(ownerId), staleTime: 30_000, refetchInterval: 60_000 });
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  async function act(action: 'sync' | 'toggle') {
    setBusy(true); setNotice(''); setError('');
    try {
      if (action === 'sync') {
        const result = await syncAnime(); client.setQueryData(key, result); setNotice(result.message);
        await client.invalidateQueries({ queryKey: ['personal-anime', ownerId] });
      } else {
        const result = await setAnimeSync(!query.data?.enabled); client.setQueryData(key, result);
        setNotice(result.enabled ? 'Automatic sync enabled: your public MAL list will be checked every six hours while this Mac is awake and online.' : 'Automatic MAL sync paused. Saved snapshots are retained.');
      }
    } catch (e) { setError(e instanceof Error ? e.message : 'Sync failed. Existing snapshots are unchanged.'); }
    finally { setBusy(false); await query.refetch(); }
  }
  const state = query.data;
  return <details className="mt-2 border-t border-term-rule2 pt-1 text-t105 text-term-muted">
    <summary className="cursor-pointer py-2 text-term-accent">MAL synchronization · {state ? state.configured ? state.enabled ? 'automatic' : 'manual' : 'setup needed' : query.isError ? 'status unavailable' : 'checking'}</summary>
    <p>Read-only access to your public MAL list. Complete successful checks preserve a new private snapshot only when list data changes. No MAL password, client secret or write permission is needed. Automatic checks require the local worker and an awake, online Mac.</p>
    {query.isError ? <p>Sync status could not be loaded. <button className={BUTTON} onClick={() => query.refetch()}>Retry sync status</button></p> : null}
    {state && !state.configured ? <p>Add <code>MAL_CLIENT_ID</code> from <a className="text-term-accent" href="https://myanimelist.net/apiconfig" target="_blank" rel="noopener noreferrer">MAL API settings ↗</a> to the server’s local environment and restart the API and anime worker. Do not paste the client secret into this app. XML imports work without it.</p> : null}
    {state?.last_success_at ? <p>Last successful public-list check: {new Date(state.last_success_at).toLocaleString()}. {state.next_sync_at ? `Next scheduled check: ${new Date(state.next_sync_at).toLocaleString()}.` : ''}</p> : <p>No successful MAL API check yet. An XML import timestamp is not source freshness.</p>}
    {state?.last_error ? <p className="text-term-bad">{state.last_error}</p> : null}
    <div className="flex flex-wrap gap-3"><button className={BUTTON} disabled={!hasSnapshot || !state?.configured || busy || state.running} onClick={() => void act('sync')}>{busy ? 'Working…' : state?.running ? 'Sync in progress…' : 'Sync MAL now'}</button><button className={BUTTON} disabled={!hasSnapshot || !state || (!state.enabled && !state.configured) || busy} onClick={() => void act('toggle')}>{state?.enabled ? 'Pause automatic MAL sync' : 'Enable automatic MAL sync'}</button></div>
    {!hasSnapshot ? <p>Import your MAL export first so the app knows which account to sync.</p> : null}
    {notice ? <p role="status" className="text-term-accent">{notice}</p> : null}
    {error ? <p role="alert" className="text-term-bad">{error}</p> : null}
  </details>;
}
