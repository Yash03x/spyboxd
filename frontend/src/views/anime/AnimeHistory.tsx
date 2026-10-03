'use client';

import { useQuery } from '@tanstack/react-query';
import { useSearchParams } from 'next/navigation';
import { useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import Panel from '../../components/terminal/Panel';
import PanelCollection from '../../components/terminal/PanelCollection';
import { PanelEmpty, panelState } from '../../components/terminal/states';
import { compareAnime, type AnimeData, type AnimeEntry } from '../../services/animeApi';
import { animeHref, ANIME_STATUSES } from '../../lib/anime';
import { toCsv } from '../../lib/csv';

const CONTROL = 'min-h-10 min-w-0 max-w-full rounded border border-term-rule bg-term-bg px-2 py-2 text-t115 text-term-ink';
const BUTTON = 'min-h-10 rounded border border-term-rule px-3 py-2 text-t11 text-term-accent disabled:opacity-50';
const LABELS: Record<string, string> = { status: 'List status', score: 'Score / 10', episodes_watched: 'Episode progress', start_raw: 'Start date', finish_raw: 'Finish date', is_rewatching: 'Rewatch flag', priority: 'Priority', times_watched_raw: 'Raw times watched', title: 'Title', media_type: 'Format', episodes: 'Catalogue episodes' };
function value(row: AnimeEntry | null, field: string) {
  if (!row) return 'Not on list';
  const v = row[field as keyof AnimeEntry];
  if (field === 'status') return ANIME_STATUSES[row.status];
  if (v == null || v === '' || v === '0000-00-00' || v === 'UNKNOWN') return field === 'score' ? 'Unscored' : 'Unknown';
  if (typeof v === 'boolean') return v ? 'Yes' : 'No';
  return String(v);
}

export default function AnimeHistory({ data, pending, ownerId }: { data?: AnimeData; pending: ReactNode; ownerId: string | null | undefined }) {
  const params = useSearchParams();
  const history = data?.history ?? [];
  const before = Number(params.get('anime_before') ?? history[1]?.id);
  const after = Number(params.get('anime_after') ?? history[0]?.id);
  const eligible = Number.isSafeInteger(before) && Number.isSafeInteger(after) && before > 0 && after > before;
  const query = useQuery({ queryKey: ['anime-comparison', ownerId, before, after], queryFn: () => compareAnime(before, after), enabled: Boolean(ownerId && data && eligible), staleTime: Infinity });
  const [kind, setKind] = useState('');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);
  const [exported, setExported] = useState('');
  const changes = query.data;
  const rows = useMemo(() => (changes?.changes ?? []).filter(row => (!kind || row.kind === kind) && (!search || row.title.toLocaleLowerCase().includes(search.toLocaleLowerCase()) || String(row.mal_id) === search)), [changes, kind, search]);
  const currentPage = Math.min(page, Math.max(0, Math.ceil(rows.length / 25) - 1));
  const error = pending ?? (!eligible ? <PanelEmpty title={history.length < 2 ? 'One more snapshot unlocks comparisons' : 'Choose an earlier and a later snapshot'} body="Import another MAL export or sync your public list. Existing snapshots are kept; the app will show additions, removals and recorded changes without inventing watch dates." /> : panelState({ isLoading: query.isLoading, error: query.error, isEmpty: false, onRetry: () => query.refetch(), errorBody: 'The comparison could not be loaded. Your snapshots are unchanged.' }));
  function choose(key: string, id: string) {
    const next = new URLSearchParams(window.location.search);
    next.set(key, id); window.history.pushState(null, '', `/anime?${next}`);
    setPage(0); setExported('');
  }
  function exportChanges() {
    const csv = toCsv(['mal_id', 'title', 'change', 'field', 'before', 'after'], rows.flatMap(row => (row.fields.length ? row.fields : ['status', 'score', 'episodes_watched']).map(field => [row.mal_id, row.title, row.kind, LABELS[field] ?? field, value(row.before, field), value(row.after, field)])));
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8;' }));
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = `spyboxd-anime-changes-${before}-${after}.csv`; anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000); setExported(`Exported all ${rows.length} matching title changes.`);
  }
  return <PanelCollection ready={Boolean(data)}>
    <Panel title="YOUR LIST, BETWEEN SNAPSHOTS" wide src="Private saved snapshots · exact MAL IDs" blurb="See what changed in your list. Snapshots record states, not the dates or reasons behind each change." stats={changes && !error ? Object.entries(changes.counts).map(([unit, big]) => ({ big: String(big), unit })) : undefined} caveat="The latest 20 saved snapshots are listed. XML import time is not export time. Current catalogue enrichment is excluded.">
      <div className="flex flex-wrap items-end gap-3 p-3 font-term-sans">
        <label className="flex min-w-0 max-w-full flex-col gap-1 text-t11">Earlier snapshot<select className={CONTROL} value={Number.isFinite(before) ? String(before) : ''} onChange={event => choose('anime_before', event.target.value)}><option value="">Choose earlier snapshot</option>{history.map(row => <option key={row.id} value={row.id}>#{row.id} · {new Date(row.imported_at).toLocaleString()} · {row.titles} titles</option>)}</select></label>
        <label className="flex min-w-0 max-w-full flex-col gap-1 text-t11">Later snapshot<select className={CONTROL} value={Number.isFinite(after) ? String(after) : ''} onChange={event => choose('anime_after', event.target.value)}><option value="">Choose later snapshot</option>{history.map(row => <option key={row.id} value={row.id}>#{row.id} · {new Date(row.imported_at).toLocaleString()} · {row.titles} titles</option>)}</select></label>
      </div>
      {error ?? <div className="p-3 font-term-sans text-t115"><p>Recorded episode balance: {(changes?.episode_balance_delta ?? 0) > 0 ? '+' : ''}{changes?.episode_balance_delta}. Includes additions, removals and corrections—not episodes watched in this interval.</p><div className="flex flex-wrap gap-4 text-term-accent"><a href={animeHref({ tab: 'library' }, String(before))}>Open earlier list →</a><a href={animeHref({ tab: 'library' }, String(after))}>Open later list →</a></div></div>}
    </Panel>
    <Panel title="EVERY CHANGE, WITH EVIDENCE" wide src="Before → after · one title per row" blurb="Filter the differences and inspect either saved entry. Unknown API-only or XML-only fields do not become invented changes.">
      {error ?? <div className="p-3 font-term-sans text-t115">
        <div className="mb-3 flex flex-wrap items-end gap-3"><label className="flex min-w-0 flex-col gap-1">Change type<select className={CONTROL} value={kind} onChange={event => { setKind(event.target.value); setPage(0); setExported(''); }}><option value="">All changes</option><option value="added">Added</option><option value="removed">Removed</option><option value="changed">Changed</option></select></label><label className="flex min-w-0 flex-col gap-1">Search changes<input className={CONTROL} value={search} onChange={event => { setSearch(event.target.value); setPage(0); setExported(''); }} /></label><button className={BUTTON} disabled={!rows.length} onClick={exportChanges}>Export changes CSV</button></div>
        {rows.length ? <ul className="m-0 list-none p-0">{rows.slice(currentPage * 25, (currentPage + 1) * 25).map(row => <li key={row.mal_id} className="border-t border-term-rule2 py-3"><div className="flex flex-wrap items-baseline justify-between gap-2"><strong className="min-w-0 break-words text-term-ink">{row.title}</strong><span className="text-t105 uppercase text-term-muted">{row.kind}</span></div><dl className="my-2">{(row.fields.length ? row.fields : ['status', 'score', 'episodes_watched']).map(field => <div key={field} className="my-1 flex flex-wrap gap-x-3"><dt className="text-term-muted">{LABELS[field] ?? field}</dt><dd className="m-0 min-w-0 break-words">{value(row.before, field)} → {value(row.after, field)}</dd></div>)}</dl><div className="flex gap-4 text-term-accent">{row.before ? <a href={animeHref({ tab: 'library', anime_id: row.mal_id }, String(before))}>Earlier entry →</a> : null}{row.after ? <a href={animeHref({ tab: 'library', anime_id: row.mal_id }, String(after))}>Later entry →</a> : null}</div></li>)}</ul> : <PanelEmpty title={changes?.changes.length ? 'No changes match these filters' : 'No comparable list changes'} body="Clear the filters or choose a different pair of snapshots. No change is also a valid result." />}
        <div className="mt-3 flex flex-wrap items-center gap-3"><span>{rows.length} matching title changes</span><button className={BUTTON} disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>Previous changes</button><button className={BUTTON} disabled={(currentPage + 1) * 25 >= rows.length} onClick={() => setPage(currentPage + 1)}>Next changes</button></div>
        {exported ? <p role="status">{exported}</p> : null}
        <details className="mt-3 text-t105 text-term-muted"><summary className="cursor-pointer py-2 text-term-accent">What this comparison can—and cannot—tell you</summary><ul className="pl-4">{changes?.limitations.map(text => <li key={text} className="my-2">{text}</li>)}</ul></details>
      </div>}
    </Panel>
  </PanelCollection>;
}
