'use client';

import Link from 'next/link';
import { useAuth } from '@clerk/nextjs';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'next/navigation';
import { useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import TerminalShell from '../../components/terminal/TerminalShell';
import Panel from '../../components/terminal/Panel';
import PanelCollection from '../../components/terminal/PanelCollection';
import { getSection, getTab } from '../../components/terminal/sections';
import { panelState, PanelEmpty } from '../../components/terminal/states';
import { getAnime, importAnime, type AnimeData, type AnimeEntry } from '../../services/animeApi';
import { animeFilters, animeHref, ANIME_STATUSES, filterAnime, remainingEpisodes } from '../../lib/anime';
import { toCsv } from '../../lib/csv';
import { AnimeTaste, AnimeDiscover } from './AnimeTaste';

const CONTROL = 'min-h-10 min-w-0 max-w-full rounded border border-term-rule bg-term-bg px-2 py-2 text-t115 text-term-ink';
const BUTTON = 'min-h-10 rounded border border-term-rule px-3 py-2 text-t11 text-term-accent disabled:opacity-50';
const TEXT = 'p-3 font-term-sans text-t115 text-term-ink3';
const format = (value: number | null | undefined) => value == null ? '—' : value.toLocaleString('en-US');
const score = (value: number | null | undefined) => value == null ? 'Unscored' : `${value.toFixed(2)} / 10`;
const when = (value: string) => new Date(value).toLocaleString();

function AnimeLink({ row }: { row: AnimeEntry }) {
  return <a href={`https://myanimelist.net/anime/${row.mal_id}`} target="_blank" rel="noopener noreferrer" className="break-words text-term-accent hover:underline">{row.title}<span className="sr-only"> on MyAnimeList (new tab)</span></a>;
}

/** React owns these small, labelled DOM bars; text remains the nonvisual fallback. */
function BarList({ rows, unit = 'titles' }: { rows: Array<{ label: string; count: number; href?: string }>; unit?: string }) {
  const maximum = Math.max(1, ...rows.map((row) => row.count));
  return <ul className="m-0 list-none space-y-3 p-3">{rows.map((row) => <li key={row.label}>
    <div className="mb-1 flex items-baseline justify-between gap-3 font-term-sans text-t115">
      {row.href ? <Link href={row.href} className="min-w-0 break-words py-1 text-term-accent">{row.label}</Link> : <span>{row.label}</span>}
      <span className="shrink-0 text-term-ink">{format(row.count)} <span className="text-term-muted">{unit}</span></span>
    </div>
    <div aria-hidden="true" className="h-1.5 bg-term-rule2"><div className="h-full bg-term-accent" style={{ width: `${row.count / maximum * 100}%` }} /></div>
  </li>)}</ul>;
}

function SmallTitles({ rows, progress = false }: { rows: AnimeEntry[]; progress?: boolean }) {
  return rows.length ? <ol className="m-0 list-none p-0">{rows.map((row) => <li key={row.mal_id} className="flex items-start justify-between gap-4 border-b border-term-rule2 px-3 py-2 font-term-sans text-t115">
    <div className="min-w-0"><AnimeLink row={row} /><div className="mt-1 text-t105 text-term-muted">{row.media_type} · {ANIME_STATUSES[row.status]}{row.priority === 'HIGH' ? ' · High priority' : ''}</div></div>
    <span className="shrink-0 text-right text-t11">{progress ? <>{row.episodes_watched} / {row.episodes ?? '?'} ep<div className="mt-1 text-term-muted">{remainingEpisodes(row) == null ? 'Remaining unknown' : `${remainingEpisodes(row)} left`}</div></> : <>{row.score} / 10</>}</span>
  </li>)}</ol> : <PanelEmpty title="No matching titles" body="This export has no titles that meet this panel’s criteria." />;
}

function Overview({ data, pending, href }: { data?: AnimeData; pending: ReactNode; href: (values: Record<string, string | number | null>) => string }) {
  const summary = data?.summary;
  const top = data?.entries.filter((row) => row.status === 'completed' && row.score !== null).sort((a, b) => (b.score! - a.score!) || a.title.localeCompare(b.title) || a.mal_id - b.mal_id).slice(0, 10) ?? [];
  const queue = data?.entries.filter((row) => ['watching', 'on_hold'].includes(row.status)).sort((a, b) =>
    (a.status === 'watching' ? 0 : 1) - (b.status === 'watching' ? 0 : 1)
    || (a.priority === 'HIGH' ? 0 : 1) - (b.priority === 'HIGH' ? 0 : 1)
    || ((remainingEpisodes(a) ?? Infinity) - (remainingEpisodes(b) ?? Infinity))
    || a.title.localeCompare(b.title)).slice(0, 10) ?? [];
  return <PanelCollection ready={Boolean(data)}>
    <Panel title="YOUR ANIME AT A GLANCE" wide src="MAL export · one row per title" blurb="Your own list, on its own scale. Anime stays separate from the film and group statistics." stats={summary ? [{ big: format(summary.total), unit: 'titles on your list' }, { big: format(summary.completed), unit: 'completed' }, { big: format(summary.episodes_watched), unit: 'episodes recorded' }, { big: summary.mean_score?.toFixed(2) ?? '—', unit: 'average / 10' }] : undefined} caveat="Episode progress is summed as exported, without inferred rewatches or runtime. Separate seasons and specials are separate titles.">
      {pending ?? <div className={`${TEXT} flex flex-wrap items-center justify-between gap-3`}><p className="m-0">{format(summary?.completion_percent)}% of your list is completed. {format(summary?.rated)} titles have a score.</p><Link className="text-term-accent" href={href({ tab: 'library' })}>Explore every title →</Link></div>}
    </Panel>
    <Panel title="YOUR LIST, BY STATUS" src="my_status" blurb="Select a status to explore its titles. Bar lengths compare counts, starting at zero.">
      {pending ?? <BarList rows={summary!.statuses.map((row) => ({ ...row, href: href({ tab: 'library', anime_status: row.key }) }))} />}
    </Panel>
    <Panel title="HOW YOU SCORE" src="my_score · 1–10" blurb="Your rating distribution, with unscored titles left out." stats={summary ? [{ big: format(summary.median_score), unit: 'median / 10' }, { big: format(summary.unrated), unit: 'unscored' }] : undefined} caveat={summary ? `${summary.high_scores} of ${summary.rated} scored titles are rated 8 or higher. These are current list scores, not how your opinions changed over time.` : undefined}>
      {pending ?? <BarList rows={summary!.scores.map((row) => ({ label: `${row.score} / 10`, count: row.count, href: href({ tab: 'library', anime_score: row.score }) }))} />}
    </Panel>
    <Panel title="YOUR FORMATS" src="series_type + my_score" blurb="TV, movies, OVAs and other formats. Averages use only scored titles, with the sample shown.">
      {pending ?? <div className="overflow-x-auto p-3"><table className="w-full text-left font-term-sans text-t11"><thead><tr className="text-term-muted"><th className="pb-2">Format</th><th>Titles</th><th>Completed</th><th>Average</th></tr></thead><tbody>{summary!.formats.map((row) => <tr key={row.label} className="border-t border-term-rule2"><th className="py-2 font-normal"><Link className="text-term-accent" href={href({ tab: 'library', anime_format: row.label })}>{row.label}</Link></th><td>{row.count}</td><td>{row.completed}</td><td>{score(row.mean_score)}<div className="text-t10 text-term-muted">n = {row.rated}</div></td></tr>)}</tbody></table></div>}
    </Panel>
    <Panel title="HIGHEST-RATED COMPLETIONS" src="my_status = completed · my_score" blurb="Your top ten scored completions. Equal scores are ordered alphabetically, not by an invented preference.">
      {pending ?? <SmallTitles rows={top} />}
    </Panel>
    <Panel title="PICK UP WHERE YOU LEFT OFF" src="watching + on_hold · episode progress" blurb="Watching first, then on hold; high-priority entries and fewer remaining episodes come first. This is your unfinished queue, not a prediction of what you will enjoy." caveat={summary ? `${format(summary.known_queue_remaining)} recorded episodes remain across titles with consistent known lengths; ${summary.queue_unknown_length} queue titles have unknown lengths.` : undefined}>
      {pending ?? <SmallTitles rows={queue} progress />}
    </Panel>
  </PanelCollection>;
}

function Timeline({ data, pending, href }: { data?: AnimeData; pending: ReactNode; href: (values: Record<string, string | number | null>) => string }) {
  const params = useSearchParams();
  const summary = data?.summary;
  const years = summary?.years.map((row) => row.period) ?? [];
  const requested = params.get('anime_timeline_year');
  const year = requested && years.includes(requested) ? requested : years.at(-1) ?? '';
  const months = Array.from({ length: 12 }, (_, index) => {
    const period = `${year}-${String(index + 1).padStart(2, '0')}`;
    const row = summary?.months.find((row) => row.period === period);
    return { period, started: row?.started ?? 0, completed: row?.completed ?? 0 };
  });
  return <PanelCollection ready={Boolean(data)}>
    <Panel title="COMPLETIONS THROUGH THE YEARS" src="my_finish_date · completed titles" blurb="Only complete recorded finish dates are counted. Select a year to open its exact titles." stats={summary ? [{ big: format(summary.dated_completions), unit: 'dated completions' }, { big: format(summary.undated_completions), unit: 'without a full finish date' }] : undefined} caveat="An empty year means no dated completions in this snapshot, not proof you watched nothing. Future dates are excluded.">
      {pending ?? (years.length ? <BarList rows={summary!.years.map((row) => ({ label: row.period, count: row.completed, href: href({ tab: 'library', anime_year: row.period, anime_status: 'completed' }) }))} /> : <PanelEmpty title="No dated timeline yet" body="Titles still count in your totals. Add complete start or finish dates on MAL and upload a new export to see them here." />)}
    </Panel>
    <Panel title="MONTH BY MONTH" src="my_start_date + my_finish_date" blurb="Starts and completions are title-level dates, not episode watches. They can happen in different months.">
      {pending ?? (years.length ? <div className="p-3"><label className="mb-3 flex items-center gap-3 font-term-sans text-t115">Timeline year<select aria-label="Timeline year" value={year} className={CONTROL} onChange={(event) => {
        const next = new URLSearchParams(window.location.search); next.set('anime_timeline_year', event.target.value); window.history.pushState(null, '', `/anime?${next}`);
      }}>{years.map((value) => <option key={value}>{value}</option>)}</select></label><table className="w-full text-left text-t11"><caption className="sr-only">Recorded starts and completions in {year}</caption><thead className="text-term-muted"><tr><th className="py-2">Month</th><th>Started</th><th>Completed</th></tr></thead><tbody>{months.map((row) => <tr key={row.period} className="border-t border-term-rule2"><th className="py-2 font-normal">{row.period}</th><td>{row.started}</td><td>{row.completed}</td></tr>)}</tbody></table></div> : <PanelEmpty title="No complete dates" body="This chart needs at least one full start or finish date." />)}
    </Panel>
    <Panel title="START TO FINISH, HONESTLY" src="finished_date − started_date" blurb="Elapsed calendar days among completed titles with both dates, excluding reversed or future dates." stats={summary ? [{ big: format(summary.median_elapsed_days), unit: 'median elapsed days' }, { big: format(summary.duration_sample), unit: 'eligible titles' }, { big: format(summary.same_day_completions), unit: 'same-day start and finish' }] : undefined} caveat="These spans include breaks and idle time. Same-day dates do not establish a binge, watch duration or viewing streak.">
      {pending ?? <div className={TEXT}><p>Start dates are usable for {format(summary!.dated_starts)} of {format(summary!.total)} titles. Finish dates are usable for {format(summary!.dated_completions)} of {format(summary!.completed)} completed titles.</p><Link className="text-term-accent" href={href({ tab: 'library', anime_year: 'undated' })}>Inspect completed titles missing full finish dates →</Link></div>}
    </Panel>
  </PanelCollection>;
}

function Library({ data, pending, href }: { data?: AnimeData; pending: ReactNode; href: (values: Record<string, string | number | null>) => string }) {
  const params = useSearchParams();
  const filters = useMemo(() => animeFilters(params), [params]);
  const [exportMessage, setExportMessage] = useState('');
  const filtered = useMemo(() => data ? filterAnime(data.entries, filters, data.summary.as_of) : [], [data, filters]);
  const page = Math.min(filters.page, Math.max(0, Math.ceil(filtered.length / 50) - 1));
  const rows = filtered.slice(page * 50, page * 50 + 50);
  const rated = filtered.filter((row) => row.score !== null);
  function update(values: Record<string, string>) {
    const next = new URLSearchParams(window.location.search); next.delete('anime_page');
    for (const [key, value] of Object.entries(values)) { next.delete(key); if (value) next.set(key, value); }
    window.history.pushState(null, '', `/anime?${next}`);
    setExportMessage('');
  }
  function exportRows() {
    if (!data) return;
    const content = toCsv(['mal_id', 'title', 'format', 'status', 'score_1_to_10', 'episodes_watched', 'total_episodes', 'start_date_raw', 'finish_date_raw', 'priority', 'times_watched_raw', 'is_rewatching', 'issues', 'genres', 'studios', 'community_score_1_to_10', 'community_source', 'metadata_fetched_at'], filtered.map((row) => [row.mal_id, row.title, row.media_type, row.status, row.score, row.episodes_watched, row.episodes, row.start_raw, row.finish_raw, row.priority, row.times_watched_raw, row.is_rewatching, row.issues.join('|'), row.metadata?.genres.join('|'), row.metadata?.studios.join('|'), row.metadata?.community_score, row.metadata?.community_source, row.metadata?.fetched_at]));
    const url = URL.createObjectURL(new Blob([content], { type: 'text/csv;charset=utf-8;' }));
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = `spyboxd-anime-${data.snapshot.username}.csv`; anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    setExportMessage(`Exported all ${filtered.length} matching titles, not just this page.`);
  }
  const issues: Record<string, string> = { progress_exceeds_total: 'Progress exceeds total episodes', finish_before_start: 'Finish before start', invalid_date: 'Invalid date', partial_date: 'Partial date', future_date: 'Future date' };
  return <PanelCollection ready={Boolean(data)}>
    <Panel title="YOUR ANIME LIBRARY" wide src="MAL XML · exact list entries" blurb="Search, filter, inspect and export your own evidence. Filters affect this library, not the full-list overview." stats={data ? [{ big: format(filtered.length), unit: `matching of ${format(data.summary.total)}` }, { big: rated.length ? (rated.reduce((sum, row) => sum + row.score!, 0) / rated.length).toFixed(2) : '—', unit: `average / 10 · n = ${rated.length}` }] : undefined}>
      {pending ?? <>
        {filters.id !== null ? <p className={TEXT}>Exact title: MAL {filters.id}. <button className="text-term-accent underline" onClick={() => update({ anime_id: '' })}>Remove exact-title filter</button></p> : null}
        <form key={params.toString()} className="flex flex-wrap items-end gap-3 border-b border-term-rule p-3 font-term-sans" onSubmit={(event) => { event.preventDefault(); const values = new FormData(event.currentTarget); update(Object.fromEntries([...values.entries()].map(([key, value]) => [key, String(value)]))); }}>
          <label className="min-w-0 flex-1 basis-48 text-t11">Title or MAL ID<input name="anime_q" type="search" maxLength={200} defaultValue={filters.q} placeholder="Search your anime…" className={`${CONTROL} mt-1 block w-full`} /></label>
          <label className="text-t11">Status<select name="anime_status" aria-label="Status" defaultValue={filters.status} className={`${CONTROL} mt-1 block`}><option value="">All statuses</option>{Object.entries(ANIME_STATUSES).map(([key, name]) => <option key={key} value={key}>{name}</option>)}</select></label>
          <label className="min-w-0 text-t11">Genre<select name="anime_genre" aria-label="Genre" defaultValue={filters.genre} className={`${CONTROL} mt-1 block max-w-[240px]`}><option value="">All genres</option>{[...new Set(data!.entries.flatMap(row => row.metadata?.genres ?? []))].sort().map(value => <option key={value}>{value}</option>)}</select></label>
          <label className="min-w-0 text-t11">Studio<select name="anime_studio" aria-label="Studio" defaultValue={filters.studio} className={`${CONTROL} mt-1 block max-w-[240px]`}><option value="">All studios</option>{[...new Set(data!.entries.flatMap(row => row.metadata?.studios ?? []))].sort().map(value => <option key={value}>{value}</option>)}</select></label>
          <label className="text-t11">List scope<select name="anime_scope" aria-label="List scope" defaultValue={filters.scope} className={`${CONTROL} mt-1 block`}><option value="">Whole list</option><option value="watched">Watched titles only</option></select></label>
          <label className="text-t11">Format<select name="anime_format" aria-label="Format" defaultValue={filters.format} className={`${CONTROL} mt-1 block`}><option value="">All formats</option>{data!.summary.formats.map((row) => <option key={row.label}>{row.label}</option>)}</select></label>
          <label className="text-t11">Score<select name="anime_score" aria-label="Score" defaultValue={filters.score} className={`${CONTROL} mt-1 block`}><option value="">All scores</option><option value="unrated">Unscored</option>{Array.from({ length: 10 }, (_, i) => <option key={i + 1} value={i + 1}>{i + 1} / 10</option>)}</select></label>
          <label className="text-t11">Completion year<select name="anime_year" aria-label="Completion year" defaultValue={filters.year} className={`${CONTROL} mt-1 block`}><option value="">Any / not completed</option><option value="undated">Missing full finish date</option>{data!.summary.years.map((row) => <option key={row.period}>{row.period}</option>)}</select></label>
          <label className="text-t11">Data check<select name="anime_issue" aria-label="Data check" defaultValue={filters.issue} className={`${CONTROL} mt-1 block`}><option value="">All entries</option>{Object.entries(issues).map(([key, label]) => <option value={key} key={key}>{label}</option>)}</select></label>
          <label className="text-t11">Sort<select name="anime_sort" aria-label="Sort" defaultValue={filters.sort} className={`${CONTROL} mt-1 block`}><option value="title">Title A–Z</option><option value="score">Highest score</option><option value="finished">Latest finish date</option><option value="remaining">Fewest episodes left</option></select></label>
          <button className={BUTTON} type="submit">Apply filters</button><Link href={href({ tab: 'library' })} className={BUTTON}>Clear filters</Link>
        </form>
        <div className="flex flex-wrap items-center gap-3 p-3"><button className={BUTTON} disabled={!filtered.length} onClick={exportRows}>Export matching CSV</button><p role="status" className="m-0 text-t11 text-term-muted">{exportMessage || 'CSV includes all matches and the original date strings.'}</p></div>
        {rows.length ? <div role="region" aria-label="Anime results table" tabIndex={0} className="overflow-x-auto"><table className="w-full min-w-[720px] border-collapse text-left font-term-sans text-t115"><caption className="sr-only">Filtered anime list, {filtered.length} matches</caption><thead className="border-y border-term-rule bg-term-panelhd text-t10 text-term-muted"><tr>{['Anime', 'Status', 'Score / 10', 'Episodes', 'Started', 'Finished'].map((label) => <th key={label} className="px-3 py-2">{label}</th>)}</tr></thead><tbody>{rows.map((row) => <tr key={row.mal_id} className="border-b border-term-rule2"><th className="w-[35%] min-w-[180px] max-w-[400px] px-3 py-3 font-normal"><AnimeLink row={row} /><div className="mt-1 text-t10 text-term-muted">{row.media_type} · MAL {row.mal_id}{row.issues.length ? ` · ${row.issues.map((key) => issues[key] ?? key).join(', ')}` : ''}</div></th><td className="px-3">{ANIME_STATUSES[row.status]}</td><td className="px-3">{row.score ?? 'Unscored'}</td><td className="whitespace-nowrap px-3">{row.episodes_watched} / {row.episodes ?? '?'}</td><td className="whitespace-nowrap px-3">{row.started_date ?? (row.start_raw && row.start_raw !== '0000-00-00' ? `${row.start_raw} (${row.start_precision})` : 'Unknown')}</td><td className="whitespace-nowrap px-3">{row.finished_date ?? (row.finish_raw && row.finish_raw !== '0000-00-00' ? `${row.finish_raw} (${row.finish_precision})` : 'Unknown')}</td></tr>)}</tbody></table></div> : <PanelEmpty title="No anime match these filters" body="Try a broader title search or clear the filters. Your imported list has not changed." />}
        <div className="flex flex-wrap items-center justify-between gap-3 p-3 text-t11"><span>{filtered.length ? `${page * 50 + 1}–${Math.min((page + 1) * 50, filtered.length)} of ${filtered.length} titles` : '0 matching titles'}</span><div className="flex gap-2"><button className={BUTTON} disabled={page === 0} onClick={() => update({ anime_page: String(page - 1) })}>Previous</button><button className={BUTTON} disabled={(page + 1) * 50 >= filtered.length} onClick={() => update({ anime_page: String(page + 1) })}>Next</button></div></div>
      </>}
    </Panel>
    <Panel title="SOURCE & DATA QUALITY" wide src="Validated MAL XML snapshot" blurb="What this export can tell you, and what it cannot.">
      {pending ?? <div className={TEXT}>
        <dl className="grid gap-2 sm:grid-cols-2"><div><dt className="text-term-muted">Source file</dt><dd className="m-0 break-all">{data!.snapshot.filename}</dd></div><div><dt className="text-term-muted">Imported into this app</dt><dd className="m-0">{when(data!.snapshot.imported_at)}</dd></div><div><dt className="text-term-muted">Date coverage</dt><dd className="m-0">{data!.summary.dated_completions} / {data!.summary.completed} completed titles have usable finish dates.</dd></div><div><dt className="text-term-muted">Identity & reconciliation</dt><dd className="m-0">Unique MAL IDs; XML total and supplied status counts validated before import.</dd></div></dl>
        <ul className="my-4 list-disc space-y-2 pl-5">{data!.limitations.map((note) => <li key={note}>{note}</li>)}</ul>
        <div className="flex flex-wrap gap-3">{Object.entries(data!.summary.issues).filter(([, count]) => count > 0).map(([key, count]) => <Link key={key} className={BUTTON} href={href({ tab: 'library', anime_issue: key })}>{issues[key] ?? key}: {count}</Link>)}<Link className={BUTTON} href={href({ tab: 'library', anime_year: 'undated' })}>Missing finish dates: {data!.summary.undated_completions}</Link></div>
        <details className="mt-4"><summary className="cursor-pointer py-2 text-term-accent">Import history & source fingerprint</summary><p className="break-all text-t10 text-term-muted">SHA-256 (decompressed XML): {data!.snapshot.sha256}</p><p className="text-t11">Prior snapshots are retained privately. Viewing one does not replace your latest import. Last 20 imports:</p><ul className="list-disc space-y-2 pl-5">{data!.history.map((row) => <li key={row.id}><Link className="text-term-accent" href={animeHref({ tab: 'library', anime_snapshot: row.id })}>{when(row.imported_at)} · {row.titles} titles{row.id === data!.snapshot.id ? ' · viewing' : ''}</Link></li>)}</ul><Link href="/anime?tab=library" className="text-term-accent">Return to latest import</Link></details>
      </div>}
    </Panel>
  </PanelCollection>;
}

export default function AnimeWorkspace() {
  const params = useSearchParams();
  const { userId, isSignedIn } = useAuth();
  const queryClient = useQueryClient();
  const section = getSection('anime');
  const tab = getTab(section, params.get('tab'));
  const requestedId = Number(params.get('anime_snapshot'));
  const snapshotId = Number.isSafeInteger(requestedId) && requestedId > 0 ? requestedId : undefined;
  const queryKey = ['personal-anime', userId, snapshotId ?? 'latest'];
  const query = useQuery({ queryKey, queryFn: () => getAnime(snapshotId), enabled: Boolean(isSignedIn && userId), staleTime: 60_000 });
  const data = query.data?.snapshot ? query.data as AnimeData : undefined;
  const input = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState('');
  const [uploadError, setUploadError] = useState('');
  const href = (values: Record<string, string | number | null>) => animeHref(values, snapshotId ? String(snapshotId) : null);
  const pending = panelState({ isLoading: query.isLoading, error: query.error, isEmpty: !data, onRetry: () => query.refetch(), errorBody: 'Your previous imports have not been changed. Retry the private Anime data request.', empty: { title: 'Bring your anime list into focus', body: 'Use Import MAL export above to upload your .xml or .xml.gz file. It stays private to your signed-in account.' } });
  async function upload(file: File) {
    setUploadError(''); setMessage('');
    if (!/\.xml(?:\.gz)?$/i.test(file.name) || file.size > 4 * 1024 * 1024 || file.size === 0) { setUploadError('Choose a non-empty MAL .xml or .xml.gz export up to 4 MiB.'); return; }
    setUploading(true);
    try {
      const result = await importAnime(file);
      queryClient.setQueryData(['personal-anime', userId, 'latest'], result);
      await queryClient.invalidateQueries({ queryKey: ['personal-anime', userId] });
      window.history.pushState(null, '', '/anime?tab=overview');
      setMessage(result.message);
    } catch (error) { setUploadError(error instanceof Error ? error.message : 'Import failed. Your previous snapshot is unchanged.'); }
    finally { setUploading(false); if (input.current) input.current.value = ''; }
  }
  const controls = <div className="mx-[14px] mt-3 border border-term-rule bg-term-panel p-3 font-term-sans">
    <div className="flex flex-wrap items-center justify-between gap-3"><div className="min-w-0"><p className="m-0 text-t115 font-semibold text-term-ink">{data ? `${data.snapshot.username} · ${format(data.summary.total)} titles` : 'Your private MyAnimeList workspace'}</p><p className="m-0 mt-1 text-t105 text-term-muted">{data ? `Imported ${when(data.snapshot.imported_at)} · snapshot, not live sync${snapshotId ? ' · viewing a saved import' : ''}` : 'Upload a MAL anime export. No MAL password or API key needed.'}</p></div>
      <input ref={input} type="file" accept=".xml,.xml.gz,application/gzip,text/xml,application/xml" className="sr-only" tabIndex={-1} aria-label="MAL export file" onChange={(event) => { const file = event.target.files?.[0]; if (file) void upload(file); }} disabled={uploading} />
      <button type="button" className={BUTTON} disabled={uploading || !isSignedIn} onClick={() => input.current?.click()}>{uploading ? 'Importing…' : 'Import MAL export'}</button>
    </div>
    {data && data.summary.undated_completions > 0 ? <p className="mb-0 mt-2 text-t105 text-term-muted">Timeline: {data.summary.dated_completions} / {data.summary.completed} completions dated. <Link className="text-term-accent" href={href({ tab: 'library', anime_year: 'undated' })}>{data.summary.undated_completions} lack a full finish date.</Link></p> : null}
    {data?.metadata_coverage ? <p className="mb-0 mt-2 text-t105 text-term-muted">Metadata: {data.metadata_coverage.enriched} / {data.metadata_coverage.total} titles · {data.metadata_coverage.stale} stale. <button className="min-h-8 px-2 text-term-accent disabled:opacity-50" disabled={query.isFetching} onClick={() => query.refetch()}>Refresh insights</button></p> : null}
    <details className="mt-1 text-t105 text-term-muted"><summary className="cursor-pointer py-2 text-term-accent">Privacy & catalogue sources</summary><p className="mt-1">Imports are saved on this app’s server for your account only. Public title IDs are looked up through AniList for catalogue metadata; your username, scores and watch history are never sent. Personal imports remain snapshots, not live MAL sync.</p>{data?.metadata_coverage?.latest_fetched_at ? <p>Latest catalogue fetch: {when(data.metadata_coverage.latest_fetched_at)}. This is not a personal-list refresh date. <a className="text-term-accent" href="https://anilist.co" target="_blank" rel="noopener noreferrer">Catalogue source: AniList ↗</a></p> : null}</details>
    {message ? <p role="status" className="mb-0 mt-2 text-t11 text-term-accent">{message}</p> : null}
    {uploadError ? <p role="alert" className="mb-0 mt-2 text-t11 text-term-accent">{uploadError}</p> : null}
  </div>;
  return <TerminalShell section={section} tabId={tab.id} controls={controls}>
    {tab.id === 'overview' ? <Overview data={data} pending={pending} href={href} /> : null}
    {tab.id === 'timeline' ? <Timeline data={data} pending={pending} href={href} /> : null}
    {tab.id === 'taste' ? <AnimeTaste data={data} pending={pending} href={href} /> : null}
    {tab.id === 'discover' ? <AnimeDiscover data={data} pending={pending} href={href} /> : null}
    {tab.id === 'library' ? <Library data={data} pending={pending} href={href} /> : null}
  </TerminalShell>;
}
