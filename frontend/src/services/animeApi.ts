import api from './api';

export type AnimeStatus = 'watching' | 'completed' | 'on_hold' | 'dropped' | 'plan_to_watch';
export interface AnimeEntry {
  mal_id: number; title: string; media_type: string; status: AnimeStatus;
  score: number | null; episodes: number | null; episodes_watched: number;
  started_date: string | null; finished_date: string | null;
  start_raw: string; finish_raw: string; start_precision: string; finish_precision: string;
  priority: string; times_watched_raw: number | null; is_rewatching: boolean; issues: string[];
  metadata?: AnimeMetadata | null;
}
export interface AnimeMetadata {
  source: string; community_source: string; genres: string[]; studios: string[]; themes: string[];
  community_score: number | null; scored_by: number | null; episode_minutes: number | null;
  duration_label: string; episodes: number | null; airing_year: number | null; season: string | null;
  fetched_at: string; stale: boolean; refresh_failed: boolean;
}
export interface AnimeTrait { label: string; titles: number; completed: number; rated: number; mean_score: number | null }
export interface AnimeComparison { mal_id: number; title: string; score: number; community_score: number; community_source: string; scored_by: number | null; delta: number }
export interface AnimePick {
  mal_id: number; title: string; media_type: string; fit: number; community_score: number | null;
  community_source?: string;
  release_status?: string | null;
  episodes: number | null; estimated_minutes: number | null;
  traits: Array<{ label: string; kind: string; sample: number; affinity: number }>;
}
export interface AnimeTaste {
  genres: AnimeTrait[]; studios: AnimeTrait[]; themes: AnimeTrait[];
  watched_titles: number; training_titles: number; training_mean: number | null;
  community_sample: number; mean_community_delta: number | null;
  higher_than_community: AnimeComparison[]; lower_than_community: AnimeComparison[];
  estimated_watched_hours: number; runtime_titles: number; progress_titles: number; inconsistent_progress_excluded: number;
  recommendations: AnimePick[]; recommendation_method: string;
}
export interface AnimeSummary {
  total: number; completed: number; rated: number; unrated: number;
  mean_score: number | null; median_score: number | null; episodes_watched: number;
  completion_percent: number | null; high_scores: number;
  statuses: Array<{ key: AnimeStatus; label: string; count: number }>;
  scores: Array<{ score: number; count: number }>;
  formats: Array<{ label: string; count: number; completed: number; rated: number; mean_score: number | null }>;
  years: Array<{ period: string; started: number; completed: number }>;
  months: Array<{ period: string; started: number; completed: number }>;
  dated_completions: number; undated_completions: number; dated_starts: number;
  duration_sample: number; median_elapsed_days: number | null; same_day_completions: number;
  known_queue_remaining: number; queue_unknown_length: number; issues: Record<string, number>; as_of: string;
}
export interface AnimeData {
  snapshot: { id: number; username: string; filename: string; imported_at: string; sha256: string; exported_at: null; private: true; source?: string; fetched_at?: string | null };
  entries: AnimeEntry[]; summary: AnimeSummary;
  history: AnimeSnapshot[];
  limitations: string[];
  taste?: AnimeTaste;
  metadata_coverage?: { total: number; enriched: number; missing: number; stale: number; oldest_fetched_at: string | null; latest_fetched_at: string | null; source: string; cache_days: number };
}
export type AnimeResponse = AnimeData | { snapshot: null };
export async function getAnime(snapshotId?: number): Promise<AnimeResponse> {
  return (await api.get('/api/anime', { params: { timezone: Intl.DateTimeFormat().resolvedOptions().timeZone, ...(snapshotId ? { snapshot_id: snapshotId } : {}) } })).data;
}
export async function importAnime(file: File): Promise<AnimeData & { created: boolean; message: string }> {
  const form = new FormData();
  form.append('file', file);
  return (await api.post('/api/anime/import', form, { headers: { 'Content-Type': 'multipart/form-data' }, params: { timezone: Intl.DateTimeFormat().resolvedOptions().timeZone } })).data;
}

export interface AnimeSnapshot { id: number; imported_at: string; titles: number; source?: string; fetched_at?: string | null }
export interface AnimeChanges {
  before: AnimeSnapshot; after: AnimeSnapshot;
  counts: { added: number; removed: number; changed: number; unchanged: number };
  episode_balance_delta: number; limitations: string[];
  changes: Array<{ mal_id: number; title: string; kind: 'added' | 'removed' | 'changed'; fields: string[]; before: AnimeEntry | null; after: AnimeEntry | null }>;
}
export interface AnimeSyncState {
  configured: boolean; enabled: boolean; interval_hours: number; running: boolean; username: string | null;
  last_attempt_at: string | null; last_success_at: string | null; next_sync_at: string | null; last_error: string | null;
}
export async function compareAnime(before: number, after: number): Promise<AnimeChanges> {
  return (await api.get('/api/anime/compare', { params: { before, after } })).data;
}
export async function getAnimeSync(): Promise<AnimeSyncState> {
  return (await api.get('/api/anime/sync')).data;
}
export async function setAnimeSync(enabled: boolean): Promise<AnimeSyncState> {
  return (await api.patch('/api/anime/sync', { enabled })).data;
}
export async function syncAnime(): Promise<AnimeSyncState & { created: boolean; message: string }> {
  return (await api.post('/api/anime/sync', null, { timeout: 120_000 })).data;
}
