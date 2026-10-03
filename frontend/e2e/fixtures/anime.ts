import type { AnimeData, AnimeEntry } from '../../src/services/animeApi';

const entries: AnimeEntry[] = Array.from({ length: 65 }, (_, i) => ({
  mal_id: i + 1, title: i === 0 ? '=Formula, "Anime"' : `Fixture Anime ${String(i + 1).padStart(2, '0')}`,
  media_type: i % 4 === 0 ? 'Movie' : 'TV', status: i < 45 ? 'completed' : i < 55 ? 'watching' : 'plan_to_watch',
  score: i < 50 ? 6 + i % 5 : null, episodes: i === 64 ? null : 12, episodes_watched: i < 45 ? 12 : i < 55 ? 3 : 0,
  started_date: i < 30 ? '2025-01-01' : null, finished_date: i < 20 ? '2025-02-01' : null,
  start_raw: i < 30 ? '2025-01-01' : '0000-00-00', finish_raw: i < 20 ? '2025-02-01' : '0000-00-00',
  start_precision: i < 30 ? 'full' : 'missing', finish_precision: i < 20 ? 'full' : 'missing',
  priority: 'LOW', times_watched_raw: 0, is_rewatching: false, issues: [],
  metadata: i === 64 ? null : { source: 'AniList', community_source: 'AniList', genres: [i % 2 ? 'Drama' : 'Action'], studios: ['Fixture Studio'], themes: [], community_score: 7.5, scored_by: 100, episode_minutes: 24, duration_label: '24 min per ep', episodes: 12, airing_year: 2020, season: 'spring', fetched_at: '2026-10-03T10:00:00Z', stale: false, refresh_failed: false },
}));
export const animeFixture: AnimeData = {
  snapshot: { id: 7, username: 'anime_fixture', filename: 'fixture.xml.gz', imported_at: '2026-10-02T12:00:00Z', sha256: 'a'.repeat(64), exported_at: null, private: true },
  entries,
  summary: {
    total: 65, completed: 45, rated: 50, unrated: 15, mean_score: 8, median_score: 8, episodes_watched: 570, completion_percent: 69.2, high_scores: 30,
    statuses: [{ key: 'watching', label: 'Watching', count: 10 }, { key: 'completed', label: 'Completed', count: 45 }, { key: 'on_hold', label: 'On hold', count: 0 }, { key: 'dropped', label: 'Dropped', count: 0 }, { key: 'plan_to_watch', label: 'Plan to watch', count: 10 }],
    scores: Array.from({ length: 10 }, (_, i) => ({ score: i + 1, count: i < 5 ? 0 : 10 })),
    formats: ['TV', 'Movie'].map((label) => { const rows = entries.filter(r => r.media_type === label); const rated = rows.filter(r => r.score !== null); return { label, count: rows.length, completed: rows.filter(r => r.status === 'completed').length, rated: rated.length, mean_score: rated.reduce((sum, r) => sum + r.score!, 0) / rated.length }; }),
    years: [{ period: '2025', started: 30, completed: 20 }], months: [{ period: '2025-01', started: 30, completed: 0 }, { period: '2025-02', started: 0, completed: 20 }],
    dated_completions: 20, undated_completions: 25, dated_starts: 30, duration_sample: 20, median_elapsed_days: 31, same_day_completions: 0, known_queue_remaining: 90, queue_unknown_length: 0, issues: {}, as_of: '2026-10-03',
  },
  history: [{ id: 7, imported_at: '2026-10-02T12:00:00Z', titles: 65 }],
  limitations: ['This is an uploaded snapshot, not a live MAL connection.', 'No runtime, episode diary, genre, studio or community-score data is present.'],
};

const watched = entries.filter(row => row.status !== 'plan_to_watch');
animeFixture.metadata_coverage = { total: 65, enriched: 64, missing: 1, stale: 0, oldest_fetched_at: '2026-10-03T10:00:00Z', latest_fetched_at: '2026-10-03T10:00:00Z', source: 'AniList', cache_days: 7 };
animeFixture.taste = {
  genres: ['Action', 'Drama'].map(label => { const rows = watched.filter(row => row.metadata?.genres.includes(label)); const rated = rows.filter(row => row.score !== null); return { label, titles: rows.length, completed: rows.filter(row => row.status === 'completed').length, rated: rated.length, mean_score: rated.reduce((sum, row) => sum + row.score!, 0) / rated.length }; }),
  studios: [{ label: 'Fixture Studio', titles: 55, completed: 45, rated: 50, mean_score: 8 }], themes: [],
  watched_titles: 55, training_titles: 50, training_mean: 8, community_sample: 50, mean_community_delta: .5,
  higher_than_community: [{ mal_id: 5, title: 'Fixture Anime 05', score: 10, community_score: 7.5, community_source: 'AniList', scored_by: 100, delta: 2.5 }],
  lower_than_community: [{ mal_id: 1, title: entries[0].title, score: 6, community_score: 7.5, community_source: 'AniList', scored_by: 100, delta: -1.5 }],
  estimated_watched_hours: 228, runtime_titles: 55, progress_titles: 55, inconsistent_progress_excluded: 0,
  recommendations: entries.filter(row => row.status === 'plan_to_watch' && row.metadata).map(row => ({ mal_id: row.mal_id, title: row.title, media_type: row.media_type, fit: .25, community_score: 7.5, episodes: row.episodes, estimated_minutes: 288, traits: [{ label: row.metadata!.genres[0], kind: 'genres', sample: 25, affinity: .25 }] })),
  recommendation_method: 'Synthetic fixture: content-based ranking, not a predicted rating or probability.',
};
