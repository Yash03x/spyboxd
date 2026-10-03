import test from 'node:test';
import assert from 'node:assert/strict';
import { animeFilters, filterAnime, remainingEpisodes, animeHref } from '../src/lib/anime.ts';
import { safeWorkspaceHref } from '../src/lib/workspacePreferences.ts';

const rows = [
  { mal_id: 1, title: 'Bravo', media_type: 'TV', status: 'completed', score: 9, episodes: 12, episodes_watched: 12, finished_date: '2025-01-01', started_date: '2025-01-01', issues: [] },
  { mal_id: 2, title: 'Alpha', media_type: 'Movie', status: 'completed', score: null, episodes: 1, episodes_watched: 1, finished_date: null, started_date: null, issues: [] },
  { mal_id: 3, title: 'Charlie', media_type: 'TV', status: 'watching', score: 9, episodes: null, episodes_watched: 2, finished_date: null, started_date: '2099-01-01', issues: [] },
  { mal_id: 4, title: 'Delta', media_type: 'TV', status: 'on_hold', score: 6, episodes: 12, episodes_watched: 13, finished_date: null, started_date: null, issues: ['progress_exceeds_total'] },
];
const select = (query) => filterAnime(rows, animeFilters(new URLSearchParams(query)), '2026-01-01');

test('anime filters combine, and unscored means null rather than zero', () => {
  assert.deepEqual(select('anime_status=completed&anime_format=TV&anime_score=9').map(r => r.mal_id), [1]);
  assert.deepEqual(select('anime_score=unrated').map(r => r.mal_id), [2]);
  assert.deepEqual(select('anime_q=2').map(r => r.mal_id), [2]);
  assert.equal(select('anime_q=no-match').length, 0);
});
test('timeline drilldowns require completed titles and valid non-future dates', () => {
  assert.deepEqual(select('anime_year=2025').map(r => r.mal_id), [1]);
  assert.deepEqual(select('anime_year=undated').map(r => r.mal_id), [2]);
  assert.deepEqual(select('anime_issue=future_date').map(r => r.mal_id), [3]);
  assert.deepEqual(select('anime_issue=progress_exceeds_total').map(r => r.mal_id), [4]);
});
test('stable sorting keeps missing values last without mutating original rows', () => {
  assert.deepEqual(select('anime_sort=score').map(r => r.mal_id), [1, 3, 4, 2]);
  assert.deepEqual(select('anime_sort=remaining').map(r => r.mal_id), [2, 1, 3, 4]);
  assert.equal(remainingEpisodes(rows[2]), null);
  assert.equal(remainingEpisodes(rows[3]), null);
  assert.equal(rows[0].title, 'Bravo');
});
test('invalid query values have safe defaults and pins preserve supported anime filters', () => {
  const filter = animeFilters(new URLSearchParams('anime_status=__proto__&anime_score=-1&anime_year=bad&anime_page=1e30&anime_sort=nope'));
  assert.equal(filter.status, ''); assert.equal(filter.score, ''); assert.equal(filter.year, ''); assert.equal(filter.page, 0); assert.equal(filter.sort, 'title');
  const href = animeHref({ tab: 'library', anime_score: 9, anime_status: 'completed' }, '123');
  assert.equal(safeWorkspaceHref(href), href);
  assert.equal(new URL(href, 'https://test').searchParams.get('anime_snapshot'), '123');
});

test('metadata filters intersect without counting unstarted titles as watched', () => {
  const input = [
    { ...rows[0], metadata: { genres: ['Drama'], studios: ['Example Studio'] } },
    { ...rows[1], metadata: { genres: ['Drama'], studios: ['Example Studio'] }, status: 'plan_to_watch', episodes_watched: 0 },
    rows[2],
  ];
  const filters = animeFilters(new URLSearchParams('anime_genre=Drama&anime_studio=Example+Studio&anime_scope=watched'));
  assert.deepEqual(filterAnime(input, filters, '2026-01-01').map(row => row.mal_id), [1]);
  const href = animeHref({ tab: 'library', anime_genre: 'Drama', anime_scope: 'watched' });
  assert.equal(safeWorkspaceHref(href), href);
});

test('exact-title drilldowns cannot include another title with the same number in its name', () => {
  const input = [rows[0], { ...rows[1], title: 'Season 1' }];
  assert.deepEqual(filterAnime(input, animeFilters(new URLSearchParams('anime_id=1')), '2026-01-01').map(row => row.mal_id), [1]);
  assert.equal(safeWorkspaceHref('/anime?tab=library&anime_id=1'), '/anime?tab=library&anime_id=1');
  assert.equal(animeFilters(new URLSearchParams('anime_id=-1')).id, null);
});
