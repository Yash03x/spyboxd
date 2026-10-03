import type { AnimeEntry, AnimeStatus } from '../services/animeApi.ts';

export const ANIME_STATUSES: Record<AnimeStatus, string> = {
  watching: 'Watching', completed: 'Completed', on_hold: 'On hold', dropped: 'Dropped', plan_to_watch: 'Plan to watch',
};
export interface AnimeFilters { q: string; id: number | null; status: string; format: string; score: string; year: string; issue: string; sort: string; page: number; genre: string; studio: string; scope: string }
export function animeFilters(params: Pick<URLSearchParams, 'get'>): AnimeFilters {
  const number = Number(params.get('anime_page'));
  const status = params.get('anime_status') ?? '';
  const score = params.get('anime_score') ?? '';
  const year = params.get('anime_year') ?? '';
  const sort = params.get('anime_sort') ?? 'title';
  const issue = params.get('anime_issue') ?? '';
  const id = Number(params.get('anime_id'));
  return {
    q: (params.get('anime_q') ?? '').slice(0, 200),
    id: Number.isSafeInteger(id) && id > 0 ? id : null,
    genre: (params.get('anime_genre') ?? '').slice(0, 100), studio: (params.get('anime_studio') ?? '').slice(0, 100),
    scope: params.get('anime_scope') === 'watched' ? 'watched' : '',
    status: Object.hasOwn(ANIME_STATUSES, status) ? status : '', format: (params.get('anime_format') ?? '').slice(0, 32),
    score: /^(unrated|[1-9]|10)$/.test(score) ? score : '',
    year: /^(undated|[1-9][0-9]{3})$/.test(year) ? year : '',
    issue: ['progress_exceeds_total', 'finish_before_start', 'invalid_date', 'partial_date', 'future_date'].includes(issue) ? issue : '',
    sort: ['title', 'score', 'finished', 'remaining'].includes(sort) ? sort : 'title',
    page: Number.isSafeInteger(number) && number >= 0 && number <= 1_000_000 ? number : 0,
  };
}
export function remainingEpisodes(row: AnimeEntry): number | null {
  return row.episodes !== null && row.episodes_watched <= row.episodes ? row.episodes - row.episodes_watched : null;
}
export function filterAnime(entries: AnimeEntry[], filters: AnimeFilters, asOf: string): AnimeEntry[] {
  const q = filters.q.trim().toLocaleLowerCase();
  return entries.filter((row) => (!q || row.title.toLocaleLowerCase().includes(q) || String(row.mal_id) === q)
    && (filters.id === null || row.mal_id === filters.id)
    && (!filters.status || row.status === filters.status)
    && (!filters.format || row.media_type === filters.format)
    && (!filters.genre || Boolean(row.metadata?.genres.includes(filters.genre)))
    && (!filters.studio || Boolean(row.metadata?.studios.includes(filters.studio)))
    && (!filters.scope || (row.status !== 'plan_to_watch' && (row.status === 'completed' || row.episodes_watched > 0)))
    && (!filters.score || (filters.score === 'unrated' ? row.score === null : row.score === Number(filters.score)))
    && (!filters.year || (row.status === 'completed' && (filters.year === 'undated' ? !row.finished_date : Boolean(row.finished_date && row.finished_date <= asOf && row.finished_date.startsWith(filters.year)))))
    && (!filters.issue || (filters.issue === 'future_date' ? [row.started_date, row.finished_date].some((date) => date !== null && date > asOf) : row.issues.includes(filters.issue))))
    .sort((a, b) => {
      let order = 0;
      if (filters.sort === 'score') order = (b.score ?? -1) - (a.score ?? -1);
      if (filters.sort === 'finished') order = (b.finished_date ?? '').localeCompare(a.finished_date ?? '');
      if (filters.sort === 'remaining') order = (remainingEpisodes(a) ?? Infinity) - (remainingEpisodes(b) ?? Infinity);
      return (Number.isNaN(order) ? 0 : order) || a.title.localeCompare(b.title) || a.mal_id - b.mal_id;
    });
}
export function animeHref(values: Record<string, string | number | null>, snapshotId?: string | null): string {
  const params = new URLSearchParams();
  if (snapshotId) params.set('anime_snapshot', snapshotId);
  for (const [key, value] of Object.entries(values)) if (value !== null && value !== '') params.set(key, String(value));
  return `/anime?${params}`;
}
