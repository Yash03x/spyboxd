'use client';

import { useSearchParams } from 'next/navigation';
import type { AnchorHTMLAttributes, ReactNode } from 'react';
import Panel from '../../components/terminal/Panel';
import PanelCollection from '../../components/terminal/PanelCollection';
import { PanelEmpty } from '../../components/terminal/states';
import type { AnimeComparison, AnimeData, AnimeTrait } from '../../services/animeApi';

type Props = { data?: AnimeData; pending: ReactNode; href: (values: Record<string, string | number | null>) => string };
const TEXT = 'p-3 font-term-sans text-t115 text-term-ink3';
const CONTROL = 'mt-1 block min-h-10 w-full min-w-0 rounded border border-term-rule bg-term-bg px-2 text-term-ink';
const BUTTON = 'min-h-10 rounded border border-term-rule px-3 py-2 text-t11 text-term-accent';
const signed = (number: number) => `${number > 0 ? '+' : ''}${number.toFixed(2)}`;
const count = (number: number) => number.toLocaleString('en-US');
const score = (number: number | null) => number == null ? 'Unknown' : `${number.toFixed(2)} / 10`;

// These evidence drilldowns deliberately navigate the document. They must
// honor the exact URL even when a preceding native-history filter reset races
// with the framework's prefetched route state (especially on mobile).
function Link(props: AnchorHTMLAttributes<HTMLAnchorElement>) {
  return <a {...props} />;
}

function update(values: Record<string, string>) {
  const next = new URLSearchParams(window.location.search);
  for (const [key, value] of Object.entries(values)) { next.delete(key); if (value) next.set(key, value); }
  window.history.pushState(null, '', `/anime?${next}`);
}

function TitleLink({ row }: { row: { mal_id: number; title: string } }) {
  return <a className="break-words text-term-accent hover:underline" href={`https://myanimelist.net/anime/${row.mal_id}`} target="_blank" rel="noopener noreferrer">{row.title}<span className="sr-only"> on MyAnimeList (new tab)</span></a>;
}

function Traits({ rows, field, href, minimum }: { rows: AnimeTrait[]; field: string; href: Props['href']; minimum: number }) {
  const shown = rows.filter(row => row.titles >= minimum).slice(0, 25);
  const max = Math.max(1, ...shown.map(row => row.titles));
  return shown.length ? <div className="p-3"><p className="mt-0 font-term-sans text-t105 text-term-muted">Top {shown.length} by watched-title count · minimum {minimum}. Select a label for the exact titles.</p><ul className="m-0 list-none space-y-3 p-0">{shown.map(row => <li key={row.label}>
    <div className="flex items-baseline justify-between gap-3 font-term-sans text-t115"><Link className="min-w-0 break-words py-1 text-term-accent" href={href({ tab: 'library', [field]: row.label, anime_scope: 'watched' })}>{row.label}</Link><span className="shrink-0">{row.titles} titles</span></div>
    <div aria-hidden="true" className="h-1.5 bg-term-rule2"><div className="h-full bg-term-accent" style={{ width: `${row.titles / max * 100}%` }} /></div>
    <p className="mb-0 mt-1 text-t105 text-term-muted">{row.completed} completed · {score(row.mean_score)} · {row.rated} scored</p>
  </li>)}</ul></div> : <PanelEmpty title="Not enough matching metadata" body="Lower the minimum, or wait for the public title-metadata backfill. Missing metadata is not counted as an unknown genre or studio." />;
}

function Differences({ rows, label }: { rows: AnimeComparison[]; label: string }) {
  return <div className="min-w-0"><h3 className="m-0 border-b border-term-rule p-3 text-t115 font-semibold">{label}</h3>{rows.length ? <ol className="m-0 list-none p-0">{rows.map(row => <li key={row.mal_id} className="border-b border-term-rule2 p-3 font-term-sans text-t115"><TitleLink row={row} /><p className="mb-0 mt-1 text-t105 text-term-muted">You {row.score}/10 · {row.community_source} {row.community_score.toFixed(2)}/10 · difference {signed(row.delta)}<br />Community sample: {row.scored_by == null ? 'unknown' : count(row.scored_by)}</p></li>)}</ol> : <p className={TEXT}>No titles on this side of the community average.</p>}</div>;
}

export function AnimeTaste({ data, pending, href }: Props) {
  const params = useSearchParams();
  const requested = Number(params.get('anime_trait_min') ?? 3);
  const minimum = [1, 3, 5, 10].includes(requested) ? requested : 3;
  const taste = data?.taste;
  const state = pending ?? (!taste ? <PanelEmpty title="Metadata insights are not available yet" body="Your imported list is safe. Public catalogue metadata is enriched separately from your personal snapshot." /> : null);
  return <PanelCollection ready={Boolean(data)}>
    <Panel title="THE GENRES YOU GRAVITATE TO" src="MAL export × cached AniList genre metadata" blurb="Watched means a completed title or recorded episode progress, excluding plan-to-watch entries. Multi-genre titles count once in each genre, so these are not shares of a whole." caveat="Metadata coverage and rating sample sizes matter. Unknown genres are excluded; low sample sizes do not establish a stable preference.">
      {state ?? <><label className={`${TEXT} block`}>Minimum titles per trait<select aria-label="Minimum titles per trait" className={CONTROL} value={minimum} onChange={event => update({ anime_trait_min: event.target.value })}>{[1, 3, 5, 10].map(value => <option key={value} value={value}>{value} titles</option>)}</select></label><Traits rows={taste!.genres} field="anime_genre" minimum={minimum} href={href} /></>}
    </Panel>
    <Panel title="THE STUDIOS IN YOUR HISTORY" src="Watched titles × AniList studio metadata" blurb="Explore the studios behind your viewing and the scores you gave their work. A co-production counts under every credited studio." caveat="Ordered by watched-title count, not a claim that a studio caused your enjoyment. The same minimum-title filter applies to genres and studios.">
      {state ?? <Traits rows={taste!.studios} field="anime_studio" minimum={minimum} href={href} />}
    </Panel>
    <Panel title="YOUR SCORES VS THE COMMUNITY" wide src="Your 1–10 scores × cached AniList community averages" blurb="Where your current scores differ most. AniList averages are divided by ten to show the 1–10 scale; they are not MAL community scores." stats={taste ? [{ big: taste.mean_community_delta == null ? '—' : signed(taste.mean_community_delta), unit: 'mean difference / 10' }, { big: count(taste.community_sample), unit: 'titles with both scores' }] : undefined} caveat="Only titles with both a personal score and a nonzero community sample are included. These differences describe taste; they do not show that either rating is more correct.">
      {state ?? <div className="grid grid-cols-1 divide-y divide-term-rule md:grid-cols-2 md:divide-x md:divide-y-0"><Differences rows={taste!.higher_than_community} label="You rated these higher" /><Differences rows={taste!.lower_than_community} label="You rated these lower" /></div>}
    </Panel>
    <Panel title="WATCH TIME, WITH THE LIMITS VISIBLE" wide src="Exported episode progress × provider average episode duration" blurb="A runtime estimate—not a record of how long you actually watched." stats={taste ? [{ big: taste.runtime_titles ? count(taste.estimated_watched_hours) : '—', unit: 'estimated hours' }, { big: `${taste.runtime_titles} / ${taste.progress_titles}`, unit: 'progressed titles covered' }] : undefined} caveat="Uses average episode duration, including openings and credits. Unknown runtimes and inconsistent progress are excluded; unrecorded rewatches, playback speed and skipped content cannot be reconstructed.">
      {state ?? <p className={TEXT}>{taste!.inconsistent_progress_excluded} inconsistent-progress titles excluded. Public catalogue facts can change independently of the immutable personal import. Estimates are based only on covered titles, not extrapolated to your whole list.</p>}
    </Panel>
  </PanelCollection>;
}

export function AnimeDiscover({ data, pending, href }: Props) {
  const params = useSearchParams();
  const taste = data?.taste;
  const format = params.get('anime_pick_format') ?? '';
  const rawMax = Number(params.get('anime_pick_max_minutes'));
  const maxMinutes = [180, 360, 720, 1440].includes(rawMax) ? rawMax : 0;
  const picks = (taste?.recommendations ?? []).filter(row => (!format || row.media_type === format) && (!maxMinutes || (row.estimated_minutes !== null && row.estimated_minutes <= maxMinutes)));
  const state = pending ?? (!taste ? <PanelEmpty title="Recommendations need metadata" body="Import your list and let the public catalogue backfill finish. Your private ratings are used locally to rank your backlog." /> : null);
  return <PanelCollection ready={Boolean(data)}>
    <Panel title="WHAT TO WATCH FROM YOUR BACKLOG" wide src="Your unstarted plan-to-watch titles × your scored viewing history" blurb="Explainable, content-based picks from titles already on your list. Completed, dropped, on-hold and in-progress entries are never suggested as unseen." stats={taste ? [{ big: count(picks.length), unit: 'matching candidates' }, { big: count(taste.training_titles), unit: 'scored watched titles informing fit' }] : undefined} caveat="Affinity is a ranking signal, not a predicted score or chance of liking a title. A higher community score only breaks ties. A time filter excludes titles without a known runtime estimate.">
      {state ?? <><form key={params.toString()} className="flex flex-wrap items-end gap-3 border-b border-term-rule p-3 font-term-sans text-t11" onSubmit={event => { event.preventDefault(); const form = new FormData(event.currentTarget); update(Object.fromEntries([...form.entries()].map(([key, value]) => [key, String(value)]))); }}>
        <label className="min-w-0 flex-1 basis-40">Pick format<select className={CONTROL} name="anime_pick_format" defaultValue={format}><option value="">All formats</option>{data!.summary.formats.map(row => <option key={row.label}>{row.label}</option>)}</select></label>
        <label className="min-w-0 flex-1 basis-40">Estimated total time<select className={CONTROL} name="anime_pick_max_minutes" defaultValue={maxMinutes || ''}><option value="">Any / unknown</option>{[180, 360, 720, 1440].map(value => <option key={value} value={value}>Up to {value / 60} hours</option>)}</select></label>
        <button className={BUTTON} type="submit">Update picks</button><button className={BUTTON} type="button" onClick={() => update({ anime_pick_format: '', anime_pick_max_minutes: '' })}>Reset picks</button>
      </form>{picks.length ? <ol className="m-0 list-none divide-y divide-term-rule p-0">{picks.slice(0, 30).map((row, index) => <li key={row.mal_id} className="p-3 font-term-sans text-t115"><div className="flex items-baseline gap-3"><span className="shrink-0 text-term-dim">{String(index + 1).padStart(2, '0')}</span><div className="min-w-0"><TitleLink row={row} /><p className="mb-0 mt-1 text-t105 text-term-muted">{row.media_type} · {row.episodes ?? '?'} episodes · {row.estimated_minutes == null ? 'Runtime unknown' : `~${(row.estimated_minutes / 60).toFixed(1)} hours total`}<br />Affinity {signed(row.fit)} · {row.community_source ?? 'Community'} {score(row.community_score)}</p></div></div><ul className="mb-0 mt-2 list-disc space-y-1 pl-7 text-t105 text-term-muted">{row.traits.map(trait => <li key={`${trait.kind}:${trait.label}`}>{trait.label}: {trait.sample} scored examples · shrunk affinity {signed(trait.affinity)}</li>)}</ul><Link className="mt-2 inline-block py-1 text-t105 text-term-accent" href={href({ tab: 'library', anime_id: row.mal_id })}>Inspect your list entry →</Link></li>)}</ol> : <PanelEmpty title="No supported picks match yet" body="Try clearing filters. Recommendations need at least ten scored watched titles, usable public metadata, and three scored examples of a matching genre or studio." />}<p className={`${TEXT} border-t border-term-rule`}>Showing the first {Math.min(picks.length, 30)} of {picks.length} matches. <Link className="text-term-accent" href={href({ tab: 'library', anime_status: 'plan_to_watch' })}>Explore the full plan-to-watch list →</Link></p></>}
    </Panel>
    <Panel title="WHY THESE PICKS, AND WHAT IS MISSING" wide src="Transparent content-based ranking · no external sharing of personal scores" blurb="The ranking is calculated on the server inside your account’s private request. It is not a trained predictive model.">
      {state ?? <div className={TEXT}><p>{taste!.recommendation_method}</p><p>Your baseline among eligible scored watched titles is {score(taste!.training_mean)}. Candidate scores do not train their own recommendation.</p><p>Confirmed unreleased or cancelled titles are excluded. Unknown release status is not proof that a title is available. New titles outside your imported backlog, sequel prerequisites and streaming availability are not evaluated. A small positive affinity is weak evidence, not a guarantee.</p><p>Public metadata covers {data!.metadata_coverage?.enriched ?? 0} of {data!.summary.total} titles. {data!.metadata_coverage?.missing ?? data!.summary.total} titles still lack metadata; {data!.metadata_coverage?.stale ?? 0} cached titles are older than seven days.</p></div>}
    </Panel>
  </PanelCollection>;
}
