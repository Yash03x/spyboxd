'use client';

import Link from 'next/link';
import { useState } from 'react';
import { usePathname, useSearchParams } from 'next/navigation';
import { useWorkspacePreferences } from '../../hooks/useWorkspacePreferences';
import { safeWorkspaceHref } from '../../lib/workspacePreferences';

const BUTTON = 'rounded border border-term-rule px-2 py-1 text-t10 text-term-accent disabled:opacity-50';

export function SaveGroup({ selected, available, hrefFor }: { selected: string[]; available: string[]; hrefFor: (profiles: string[]) => string }) {
  const { preferences, save, ready } = useWorkspacePreferences();
  const [name, setName] = useState('');
  const [message, setMessage] = useState('');
  const allowed = new Set(available.map((profile) => profile.toLowerCase()));
  return <details className="w-full font-term-sans">
    <summary className="cursor-pointer py-1 text-t11 text-term-accent">Saved groups · {preferences.groups.length}</summary>
    <form className="mt-2 flex flex-wrap items-center gap-2" onSubmit={(event) => {
      event.preventDefault();
      if (!name.trim() || !selected.length) return;
      if (preferences.groups.length >= 30) { setMessage('You can save up to 30 groups. Remove one from Your workspace first.'); return; }
      const saved = save((current) => ({ ...current, groups: [...current.groups, { id: crypto.randomUUID(), name: name.trim(), profiles: selected }] }));
      setMessage(saved ? `Saved “${name.trim()}” in this browser for your account.` : 'Browser storage is unavailable; the group was not saved.');
      if (saved) setName('');
    }}>
      <input aria-label="Saved group name" placeholder="Name this group" maxLength={50} required value={name} onChange={(event) => setName(event.target.value)} className="max-w-full rounded border border-term-rule bg-term-bg px-2 py-2 text-t11 text-term-ink" />
      <button className={BUTTON} disabled={!ready || !selected.length} type="submit">Save selected group</button>
      {preferences.groups.map((group) => group.profiles.every((profile) => allowed.has(profile))
        ? <Link key={group.id} className={BUTTON} href={hrefFor(group.profiles)} scroll={false}>{group.name} · {group.profiles.length}</Link>
        : <span key={group.id} className="text-t10 text-term-muted">{group.name} · some profiles unavailable in this scope</span>)}
    </form>
    <p role="status" className="my-2 text-t105 text-term-muted">{message || 'Saved on this browser, scoped to your signed-in account. Loading a group preserves the other filters.'}</p>
  </details>;
}

export function PinStatistic({ title, panelId, pinParams }: { title: string; panelId: string; pinParams?: Record<string, string | string[]> }) {
  const { preferences, save, ready } = useWorkspacePreferences();
  const pathname = usePathname();
  const params = useSearchParams();
  const [error, setError] = useState('');
  const search = new URLSearchParams(params.toString());
  // Resolve defaults into the bookmark. Otherwise a pin made without an
  // explicit subject would silently follow whichever profile sorts first later.
  for (const [key, value] of Object.entries(pinParams ?? {})) {
    search.delete(key);
    (Array.isArray(value) ? value : [value]).forEach((item) => search.append(key, item));
  }
  const contextReady = Object.values(pinParams ?? {}).every((value) => value.length > 0);
  const href = safeWorkspaceHref(`${pathname}${search.size ? `?${search}` : ''}#${panelId}`);
  const names = pinParams?.subject ? [pinParams.subject] : pinParams?.profiles ?? [];
  const savedTitle = names.length ? `${title} · ${[names].flat().map((name) => `@${name}`).join(', ')}` : title;
  const saved = preferences.statistics.some((statistic) => statistic.href === href);
  return <span className="flex shrink-0 flex-wrap items-center gap-1">
    <button type="button" className={BUTTON} disabled={!ready || !href || !contextReady} aria-label={`${saved ? 'Unpin' : 'Pin'} ${title}`} aria-pressed={saved} onClick={() => {
      if (!href) return;
      if (!saved && preferences.statistics.length >= 40) { setError('40 pins maximum'); return; }
      const success = save((current) => ({ ...current, statistics: saved ? current.statistics.filter((statistic) => statistic.href !== href) : [...current.statistics, { title: savedTitle, href }] }));
      setError(success ? '' : 'Storage unavailable');
    }}>{saved ? 'Pinned' : 'Pin'}</button>
    {error ? <span role="status" className="text-t9 text-term-muted">{error}</span> : null}
  </span>;
}

export default function SavedWorkspace() {
  const { preferences, save } = useWorkspacePreferences();
  const [message, setMessage] = useState('');
  return <details className="mt-2 border-b border-term-rule pb-2 font-term-sans">
    <summary className="cursor-pointer py-1 text-t115 text-term-accent">Your workspace · {preferences.groups.length} groups · {preferences.statistics.length} pinned stats</summary>
    <p className="text-t105 text-term-muted">Saved only in this browser for this account. Pins preserve the selected profiles and filters; source permissions are still checked when opened.</p>
    <div className="grid gap-3 py-2 sm:grid-cols-2">
      <div><h3 className="text-t115">Saved groups</h3>{!preferences.groups.length ? <p className="text-t11 text-term-muted">Save a selected group from Films, Tonight or Overlaps.</p> : null}{preferences.groups.map((group) => {
        const next = new URLSearchParams({ tab: 'trends' });
        group.profiles.forEach((profile) => next.append('profiles', profile));
        return <div key={group.id} className="my-2 flex flex-wrap items-center gap-2"><Link className="text-t11 text-term-accent" href={`/films?${next}`}>{group.name} · {group.profiles.length} profiles</Link><button className={BUTTON} aria-label={`Remove saved group ${group.name}`} onClick={() => setMessage(save((current) => ({ ...current, groups: current.groups.filter((item) => item.id !== group.id) })) ? 'Saved group removed. Profile data was not changed.' : 'Browser storage is unavailable.')}>Remove</button></div>;
      })}</div>
      <div><h3 className="text-t115">Pinned statistics</h3>{!preferences.statistics.length ? <p className="text-t11 text-term-muted">Use Pin on an Overview, individual or pair statistic.</p> : null}{preferences.statistics.map((statistic) => <div key={statistic.href} className="my-2 flex flex-wrap items-center gap-2"><Link className="text-t11 text-term-accent" href={statistic.href}>{statistic.title}</Link><button className={BUTTON} aria-label={`Remove pinned statistic ${statistic.title}`} onClick={() => setMessage(save((current) => ({ ...current, statistics: current.statistics.filter((item) => item.href !== statistic.href) })) ? 'Statistic unpinned.' : 'Browser storage is unavailable.')}>Remove</button></div>)}</div>
    </div>
    <p role="status" className="text-t11 text-term-muted">{message}</p>
  </details>;
}
