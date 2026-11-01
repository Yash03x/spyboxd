'use client';

import { useQuery } from '@tanstack/react-query';
import { useSearchParams } from 'next/navigation';
import Panel from '../../components/terminal/Panel';
import { PanelEmpty, panelState } from '../../components/terminal/states';
import { insightsApi } from '../../services/api';

const CONTROL = 'min-h-10 w-full min-w-0 rounded border border-term-rule bg-term-bg px-2 text-term-ink';
const TEXT = 'p-3 font-term-sans text-t115 text-term-ink3';
const DIMENSIONS = ['theme', 'microgenre'] as const;

export default function MicrogenresTab({ profiles }: { profiles: string[] }) {
  const params = useSearchParams();
  const dimension = params.get('category') === 'theme' ? 'theme' : 'microgenre';
  const sort = params.get('category_order') === 'alignment' ? 'alignment' : 'watched';
  const search = (params.get('category_q') ?? '').slice(0, 100);
  const minimum = params.get('category_min') === '1' ? 1 : 3;
  const query = useQuery({
    queryKey: ['film-microgenres', profiles, sort],
    queryFn: () => insightsApi.getTasteDna(profiles, { dimensions: [...DIMENSIONS], limit: 50, sort, neighbors: false }),
    enabled: profiles.length > 0, staleTime: 300_000,
  });
  const traits = (query.data?.dimensions[dimension] ?? []).filter(trait =>
    (trait.unique_films ?? 0) >= minimum && trait.label.toLocaleLowerCase().includes(search.toLocaleLowerCase()));
  const selected = traits.find(trait => trait.id === params.get('category_id')) ?? traits[0];
  const showAll = params.get('category_rows') === 'all';
  const shown = showAll ? traits : traits.slice(0, 12);
  const coverage = query.data?.trait_coverage?.[dimension];
  function update(values: Record<string, string>) {
    const next = new URLSearchParams(window.location.search);
    for (const [key, value] of Object.entries(values)) { next.delete(key); if (value) next.set(key, value); }
    window.history.pushState(null, '', `/films?${next}`);
  }
  const pending = panelState({ isLoading: query.isLoading, error: query.error,
    isEmpty: !traits.length, onRetry: () => query.refetch(),
    empty: { title: 'No matching categories yet', body: 'Try a broader search or include one-film categories. Films need plot keywords to appear here.' } });

  return <>
    <Panel title="BEYOND BROAD GENRES" src="TMDB plot keywords × genres"
      blurb="Find the subjects each person returns to, then explore more specific combinations such as Science Fiction · time travel. Select a category to see its films."
      stats={coverage ? [{ big: `${coverage.films} / ${coverage.total_films}`, unit: 'distinct films with categories' }] : undefined}
      caveat="Showing up to 50 categories per view before filters. A sample counts profile-film pairs; one film watched by three people contributes three observations. Minimum size counts distinct films. Rating averages exclude unscored watches.">
      <div className="grid grid-cols-1 gap-3 p-3 font-term-sans text-t11 sm:grid-cols-2">
        <label>Category type<select aria-label="Category type" className={CONTROL} value={dimension} onChange={event => update({ category: event.target.value, category_id: '' })}><option value="microgenre">Microgenres</option><option value="theme">Plot themes</option></select></label>
        <label>Search loaded categories<input aria-label="Search loaded categories" maxLength={100} className={CONTROL} value={search} onChange={event => update({ category_q: event.target.value, category_id: '' })} /></label>
        <label>Minimum distinct films<select aria-label="Minimum distinct films" className={CONTROL} value={minimum} onChange={event => update({ category_min: event.target.value, category_id: '' })}><option value="3">3 films</option><option value="1">1 film</option></select></label>
        <label>Order categories<select aria-label="Order categories" className={CONTROL} value={sort} onChange={event => update({ category_order: event.target.value, category_id: '' })}><option value="watched">Most watched</option><option value="alignment">Taste alignment</option></select></label>
      </div>
      {pending ?? <><ul aria-label="Taste categories" className="m-0 grid list-none grid-cols-1 gap-2 p-3 xl:grid-cols-2">{shown.map(trait => <li key={trait.id} className="min-w-0 border border-term-rule p-3 font-term-sans text-t115">
        <button type="button" aria-pressed={selected?.id === trait.id} className="min-h-10 w-full break-words text-left text-term-accent underline underline-offset-4" onClick={() => { update({ category_id: trait.id }); document.getElementById('insight-microgenre-evidence')?.scrollIntoView({ block: 'nearest' }); }}>{trait.label}</button>
        <p className="mb-0 mt-1 text-t105 text-term-muted">{trait.unique_films} films · {trait.sample_size} observations · {trait.average_rating == null ? 'Unrated' : `${trait.average_rating.toFixed(2)}★ average`}</p>
        <p className="mb-0 mt-1 break-words text-t105 text-term-muted">{trait.per_profile.filter(person => person.sample_size > 0).map(person => `@${person.username}: ${person.sample_size} watched, ${person.rated_sample_size} rated`).join(' · ')}</p>
      </li>)}</ul>{traits.length > 12 ? <button type="button" className="m-3 min-h-10 border border-term-rule px-3 text-term-accent" onClick={() => update({ category_rows: showAll ? '' : 'all' })}>{showAll ? 'Show the first 12 categories' : `Show all ${traits.length} matching categories`}</button> : null}</>}
      <details className={`${TEXT} border-t border-term-rule`}><summary className="cursor-pointer text-term-accent">How these categories work</summary><p>Plot themes come from TMDB keywords, with common production labels omitted. A microgenre combines one recorded genre with one plot theme. A film can belong to several categories. These are Spyboxd categories; Nanocrowd uses a separate licensed audience-reaction dataset.</p><p>Taste alignment orders categories by ratings across every selected person and demotes small or one-sided samples. Watching a theme does not establish liking it. Unmatched films are omitted; plot keywords can contain spoilers.</p></details>
    </Panel>
    <Panel panelId="insight-microgenre-evidence" title="THE FILMS BEHIND THE CATEGORY" src="Actual selected-profile film records" blurb={selected ? selected.label : 'Choose a category to inspect the evidence.'}>
      {pending ?? (selected?.examples?.length ? <><ul className="m-0 grid list-none grid-cols-1 gap-3 p-3 font-term-sans text-t115 md:grid-cols-2">{selected.examples.map(example => <li key={example.movie.movie_id} className="min-w-0 border border-term-rule p-3"><p className="m-0 break-words font-semibold">{example.movie.title}{example.movie.year ? ` (${example.movie.year})` : ''}</p><p className="mb-0 mt-2 break-words text-t105 text-term-muted">Watched by {example.watched_by.map(name => `@${name}`).join(', ')}</p></li>)}</ul><p className={TEXT}>Showing {selected.examples.length} of {selected.unique_films} distinct films, ordered by title. A listed viewer watched the film; the list does not imply a shared viewing session.</p></> : <PanelEmpty title="No film evidence available" body="Choose another category or refresh the request." />)}
    </Panel>
  </>;
}
