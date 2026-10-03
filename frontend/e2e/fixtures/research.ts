import type { ResearchResponse, ResearchSummary } from '../../src/services/researchApi';

/** Deterministic data for UI contracts; backend tests verify the calculation. */
export function researchFixture(url: URL): ResearchResponse {
  const params = url.searchParams;
  const members = params.getAll('profiles');
  const comparison = params.getAll('compare_profiles');
  const start = params.get('from') || '2026-07-01';
  const end = params.get('to') || '2026-07-31';
  const search = params.get('q')?.toLowerCase() || '';
  const trait = params.get('trait') || '';
  const rows = Array.from({ length: 60 }, (_, i) => {
    const username = i < 55 ? 'alpha' : 'bravo';
    return { event_id: i + 1, movie_id: i + 1, title: i === 0 ? '=Fixture formula' : `Evidence Film ${String(i + 1).padStart(2, '0')}`, year: 2024, username,
      groups: [...(members.includes(username) ? ['A'] : []), ...(comparison.includes(username) ? ['B'] : [])],
      date: `2026-07-${String((i % 28) + 1).padStart(2, '0')}`, watched_date: '2026-07-01', logged_date: null,
      rating: i % 5 ? 4 : null, rewatch: false, source_kind: 'diary', film_url: 'https://letterboxd.com/film/fixture/' };
  }).filter((row) => row.groups.length && row.date >= start && row.date <= end && (!search || `${row.title} ${row.username}`.toLowerCase().includes(search)) && (!trait || trait === 'Drama'));
  const summary = (selected: typeof rows, people: string[]): ResearchSummary => ({ watches: selected.length, films: selected.length, rated: selected.filter((r) => r.rating !== null).length, average_rating: selected.length ? 4 : null, rewatches: 0, members: people.length, active_members: new Set(selected.map((r) => r.username)).size, watches_per_member_30_days: selected.length / Math.max(people.length, 1), low_rating_sample: selected.length < 10 });
  if (params.get('sort') === 'title') rows.sort((a, b) => a.title.localeCompare(b.title));
  else rows.sort((a, b) => b.date.localeCompare(a.date) || a.event_id - b.event_id);
  const offset = Number(params.get('offset') || 0);
  const limit = Number(params.get('limit') || 50);
  const groups = [{ label: 'A', people: members }, ...(comparison.length ? [{ label: 'B', people: comparison }] : [])].map(({ label, people }) => {
    const own = rows.filter((r) => r.groups.includes(label));
    return { label, profiles: people, current: summary(own, people), previous: summary([], people), change: { watches: own.length, watches_percent: null, rating: null }, per_profile: people.map((username) => ({ username, ...summary(own.filter((r) => r.username === username), [username]) })), monthly: [], traits: own.length ? [{ label: 'Drama', ...summary(own, people) }] : [] };
  });
  return { period: { from: start, to: end, days: 31, previous_from: '2026-05-31', previous_to: '2026-06-30', basis: params.get('basis') || 'watched' }, groups, evidence: { rows: rows.slice(offset, offset + limit), total: rows.length, offset, limit }, facets: ['Drama'], coverage: { status: 'partial', undated_known_watches: 5, warnings: ['5 known watches have no diary date; period comparisons cannot include them.', ...(comparison.some((p) => members.includes(p)) ? ['Groups share members; their observations are not independent and must not be added together.'] : [])] }, method: 'One watch is one recorded diary event. Equal-length periods; descriptive means, not population estimates.' };
}

export function evaluationFixture(profiles: string[]) {
  return { status: 'available', top_k: 5, members_evaluated: profiles.length, members_selected: profiles.length,
    equal_member_mean: 3.8, worst_member_mean: 3.5, baseline_equal_member_mean: 3.9,
    per_profile: profiles.map((username) => ({ username, eligible_movies: 15, evaluated: true, held_out_mean: 3.8, mean_only_baseline: 3.9, low_rated_picks: 1, picks: 5, examples: [{ movie_id: 1, title: 'Held Out Fixture Film', held_out_rating: 4 }] })),
    method: 'Hide one member’s ratings. Each member has equal weight.', limitations: 'Rating component only. Not a temporal backtest or a prediction of future satisfaction.' };
}
