import axios, { AxiosHeaders } from 'axios';

// Create axios instance with base configuration
const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000',
  headers: {
    'Content-Type': 'application/json',
  },
});

type TokenProvider = () => Promise<string | null>;

let tokenProvider: TokenProvider | null = null;

export function setApiTokenProvider(provider: TokenProvider | null) {
  tokenProvider = provider;
}

api.interceptors.request.use(async (config) => {
  const headers = AxiosHeaders.from(config.headers);
  if (!tokenProvider) {
    headers.delete('Authorization');
    config.headers = headers;
    return config;
  }

  try {
    const token = await tokenProvider();
    if (token) {
      headers.set('Authorization', `Bearer ${token}`);
    } else {
      headers.delete('Authorization');
    }
  } catch (error) {
    console.error('Failed to fetch auth token for API request:', error);
    headers.delete('Authorization');
  }

  config.headers = headers;
  return config;
});

// Types for API responses
export interface DataCoverage {
  mode: string;
  source: string;
  is_partial: boolean | null;
  summary: string;
  limitations: string[];
  stats_label: string;
  profile_metadata_available?: boolean;
  watchlist_available?: boolean;
  lists_available?: boolean;
}

export interface ProfileInfo {
  username: string;
  display_name?: string | null;
  profile_image_url?: string | null;
  avatar_url?: string | null;
  total_films: number;   // All films discovered
  rated_films: number;   // Films with ratings
  liked_films: number;   // Films that are liked
  avg_rating: number;
  total_reviews: number;
  join_date: string | null;
  last_scraped_at?: string | null;
  scraping_status?: string;
  data_coverage?: DataCoverage;
}

export interface CurrentUser {
  user_id: string;
  is_admin: boolean;
}

export type ProfileRequestStatus = 'pending' | 'approved' | 'rejected' | 'fulfilled';

export interface ProfileRequestProfile {
  id: number;
  username: string;
  display_name: string | null;
  profile_image_url: string | null;
  scraping_status: string;
  is_active: boolean;
}

export interface ProfileRequest {
  id: number;
  requested_username: string;
  status: ProfileRequestStatus;
  requested_at: string;
  updated_at: string;
  resolved_at: string | null;
  profile: ProfileRequestProfile | null;
}

export interface AdminProfileRequest extends ProfileRequest {
  requester_user_id: string;
  note: string | null;
  resolved_by_user_id: string | null;
}

export interface ProfileRequestSubmission {
  message: string;
  status: 'tracked' | 'pending';
  profile: ProfileRequestProfile | null;
  request: ProfileRequest | null;
}

export const authApi = {
  getCurrentUser: async (): Promise<CurrentUser> => {
    const response = await api.get('/api/me');
    return response.data;
  },
};

export interface ProfileAnalysis {
  username: string;
  total_films: number;
  rated_films: number;
  liked_films: number;
  avg_rating: number;
  total_reviews: number;
  join_date: string | null;
  last_scraped_at: string | null;
  scraping_status: string;
  enhanced_metrics: Record<string, unknown>;
  data_coverage?: DataCoverage;
  rating_distribution: Record<string, number>;
  monthly_stats: ActivityData[];
  recent_ratings: RecentRating[];
  recent_reviews: RecentReview[];
  recent_watching_trend: RecentWatchEvent[];
}

export interface RecentRating {
  movie_title: string;
  movie_year: number | null;
  rating: number | null;
  watched_date: string | null;
  is_rewatch: boolean;
}

export interface RecentReview {
  movie_title: string;
  movie_year: number | null;
  rating: number | null;
  review_text: string | null;
  published_date: string | null;
  likes_count: number;
}

export interface RecentWatchEvent {
  movie_title: string;
  movie_year: number | null;
  watched_date: string | null;
  rating: number | null;
  is_rewatch: boolean;
}

export interface UploadFilesOptions {
  publish_owner_data?: boolean;
}

// Profile API endpoints
export const profileApi = {
  // Get all profiles
  getProfiles: async (): Promise<ProfileInfo[]> => {
    const response = await api.get('/profiles/');
    return response.data.profiles || [];
  },

  // Get profile analysis
  getAnalysis: async (username: string): Promise<ProfileAnalysis> => {
    const response = await api.get(`/profiles/${username}/analysis`);
    return response.data;
  },

  // Upload ZIP files
  uploadFiles: async (files: FileList, options: UploadFilesOptions = {}): Promise<{
    loaded_profiles: string[];
    imports?: Array<{
      username: string;
      source_kind: string;
      movies_loaded: number;
    }>;
    errors?: string[];
  }> => {
    const formData = new FormData();
    Array.from(files).forEach((file) => {
      formData.append(`files`, file);
    });
    formData.append('publish_owner_data', String(options.publish_owner_data ?? false));
    
    const response = await api.post('/upload/', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
    return response.data;
  },

  // Create profile
  createProfile: async (username: string): Promise<{ message: string; profile: any }> => {
    const response = await api.post('/profiles/create', { username });
    return response.data;
  },

  // Delete profile
  deleteProfile: async (username: string): Promise<{ message: string }> => {
    const response = await api.delete(`/profiles/${username}`);
    return response.data;
  },

  getRequests: async (): Promise<ProfileRequest[]> => {
    const response = await api.get('/profiles/requests');
    return response.data.requests || [];
  },

  requestProfile: async (username: string): Promise<ProfileRequestSubmission> => {
    const response = await api.post('/profiles/requests', { username });
    return response.data;
  },

  stopTracking: async (username: string): Promise<{ message: string; status: 'untracked'; username: string }> => {
    const response = await api.delete(`/profiles/${encodeURIComponent(username)}/tracking`);
    return response.data;
  },
};

export const adminProfileRequestApi = {
  getRequests: async (status?: ProfileRequestStatus): Promise<AdminProfileRequest[]> => {
    const response = await api.get('/admin/profile-requests', {
      params: status ? { status } : undefined,
    });
    return response.data.requests || [];
  },

  updateRequest: async (
    id: number,
    status: Extract<ProfileRequestStatus, 'approved' | 'rejected'>,
    note?: string,
  ): Promise<{ message: string; request: AdminProfileRequest }> => {
    const response = await api.put(`/admin/profile-requests/${id}`, { status, note });
    return response.data;
  },
};

export interface SystemStats {
  total_profiles: number;
  total_movies_tracked: number;
  total_reviews: number;
  global_avg_rating: number;
  last_updated: string;
}

export interface TopMovie {
  title: string;
  year: number | null;
  average_rating: number;
  total_ratings: number;
}

export interface ActivityData {
  month: string;
  movies_watched: number;
  average_rating: number | null;
}

export interface GroupSignalMovie {
  title: string;
  year: number | null;
  profile_count: number;
  profiles: string[];
  rating_count: number;
  average_rating: number | null;
  rating_stddev: number | null;
  max_rating_gap: number | null;
  liked_count: number;
  rewatch_count: number;
}

export interface GroupSignalParticipant {
  username: string;
  rating: number | null;
  watched_date: string | null;
  is_rewatch: boolean;
}

export interface GroupSignalEvent {
  title: string;
  year: number | null;
  start_date: string;
  end_date: string;
  profile_count: number;
  pair_count: number;
  profiles: string[];
  participants: GroupSignalParticipant[];
  average_rating: number | null;
  max_rating_gap: number | null;
  rewatch_count: number;
  day_gap?: number;
}

export interface GroupSignalPair {
  profiles: string[];
  shared_titles: number;
  same_day_count: number;
  one_day_gap_count: number;
  tight_window_count: number;
  within_gap_count?: number;
  rating_overlap_count: number;
  rating_correlation: number | null;
  average_rating_gap: number | null;
  alignment_score: number;
  sample_titles: Array<{
    title: string;
    year: number | null;
  }>;
}

export interface GroupSignalFollowPath {
  leader: string;
  follower: string;
  next_day_overlap_count: number;
  sample_titles: Array<{
    title: string;
    year: number | null;
  }>;
}

export interface GroupSignalsSummary {
  profiles_analyzed: number;
  profiles_with_diary_dates: number;
  shared_titles: number;
  same_day_events: number;
  one_day_gap_events: number;
  same_day_pair_hits: number;
  one_day_gap_pair_hits: number;
  gap_days?: number;
  gap_events?: number;
  gap_pair_hits?: number;
  most_shared_title: GroupSignalMovie | null;
  strongest_alignment_pair: GroupSignalPair | null;
  most_divisive_title: GroupSignalMovie | null;
}

export interface GroupSignals {
  summary: GroupSignalsSummary;
  same_day_events: GroupSignalEvent[];
  one_day_gap_events: GroupSignalEvent[];
  gap_events?: GroupSignalEvent[];
  most_shared_titles: GroupSignalMovie[];
  consensus_hits: GroupSignalMovie[];
  divisive_titles: GroupSignalMovie[];
  aligned_pairs: GroupSignalPair[];
  follow_paths: GroupSignalFollowPath[];
}

export interface SpySignalsResponse {
  selected_profiles: string[];
  gap_days: number;
  group_signals: GroupSignals;
}

export interface RewatchEchoParticipant extends GroupSignalParticipant {
  liked: boolean;
  watch_kind: 'first_known_watch' | 'rewatch';
  classification_basis:
    | 'letterboxd_rewatch_flag'
    | 'earlier_observed_event'
    | 'earliest_observed_unmarked_event';
  timing_role: 'same_day' | 'leader' | 'follower';
}

export interface RewatchEcho {
  echo_id: string;
  movie: MovieSummary;
  pattern: 'first_known_plus_rewatch' | 'rewatch_plus_rewatch';
  timing: 'same_day' | 'within_gap';
  start_date: string;
  end_date: string;
  day_gap: number;
  participants: RewatchEchoParticipant[];
}

export interface RewatchEchoesResponse {
  selected_profiles: string[];
  gap_days: number;
  coverage: FeatureCoverage;
  summary: {
    echoes: number;
    movies: number;
    same_day: number;
    within_gap: number;
    first_known_plus_rewatch: number;
    rewatch_plus_rewatch: number;
    date_coverage_ratio: number | null;
  };
  echoes: RewatchEcho[];
}

export interface DashboardAnalytics {
  system_stats: SystemStats;
  top_rated_movies: TopMovie[];
  rating_distribution: Record<string, number>;
  activity_data: ActivityData[];
  group_signals: GroupSignals;
  timestamp: string;
}

// Dashboard API endpoints
export const dashboardApi = {
  // Get dashboard analytics
  getAnalytics: async (): Promise<DashboardAnalytics> => {
    const response = await api.get('/api/dashboard/analytics');
    return response.data;
  },
};

// Focused co-watch signal API endpoints
export const spySignalsApi = {
  getSignals: async (profiles: string[], gapDays: number): Promise<SpySignalsResponse> => {
    const params = new URLSearchParams();
    profiles.forEach((profile) => params.append('profiles', profile));
    params.set('gap_days', String(gapDays));
    params.set('event_source', 'events');

    const response = await api.get('/api/spy-signals', { params });
    return response.data;
  },

  getRewatchEchoes: async (profiles: string[], gapDays: number): Promise<RewatchEchoesResponse> => {
    const params = new URLSearchParams();
    profiles.forEach((profile) => params.append('profiles', profile));
    params.set('gap_days', String(gapDays));

    const response = await api.get('/api/rewatch-echoes', { params });
    return response.data;
  },
};

export type FeatureReadinessStatus = 'ready' | 'partial' | 'blocked';

export interface FeatureCoverage {
  status: FeatureReadinessStatus;
  score: number;
  dated_watch_events: number;
  total_watch_events: number;
  blockers: string[];
  warnings: string[];
  last_updated: string | null;
}

export interface ProfileRef {
  username: string;
  display_name?: string | null;
  avatar_url?: string | null;
  total_films?: number;
}

export interface MovieSummary {
  movie_id: number | null;
  tmdb_id: number | null;
  letterboxd_slug: string | null;
  title: string;
  year: number | null;
  poster_url: string | null;
}

export interface PairMovieObservation {
  username: string;
  rating: number | null;
  watched_dates: string[];
  liked: boolean;
  rewatch_count: number;
  review_text?: string | null;
  review_date?: string | null;
}

export interface PairMovieComparison {
  movie: MovieSummary;
  observations: PairMovieObservation[];
  rating_gap: number | null;
  minimum_watch_gap_days: number | null;
}

export interface PairInfluencePath {
  leader: string;
  follower: string;
  movie: MovieSummary;
  leader_date: string;
  follower_date: string;
  gap_days: number;
}

export interface PairDossierResponse {
  selected_profiles: string[];
  coverage: FeatureCoverage;
  summary: {
    shared_titles: number;
    rated_overlap: number;
    same_day_events: number;
    within_gap_events: number;
    alignment_score: number | null;
    rating_correlation: number | null;
    average_rating_gap: number | null;
    directional_leader: string | null;
    date_coverage_ratio?: number | null;
  };
  co_watches: GroupSignalEvent[];
  influence_paths: PairInfluencePath[];
  agreements: PairMovieComparison[];
  disagreements: PairMovieComparison[];
  monthly_alignment: Array<{
    month: string;
    overlap_count: number;
    correlation: number | null;
    average_rating_gap: number | null;
  }>;
}

export type TasteDimension =
  | 'genre'
  | 'director'
  | 'actor'
  | 'language'
  | 'country'
  | 'decade'
  | 'keyword'
  | 'runtime';

export interface TasteTraitProfileScore {
  username: string;
  score: number;
  sample_size: number;
  average_rating: number | null;
}

export interface TasteTrait {
  id: string;
  label: string;
  dimension: TasteDimension;
  group_score: number;
  sample_size: number;
  average_rating: number | null;
  like_rate: number | null;
  watch_share: number;
  per_profile: TasteTraitProfileScore[];
  top_movies: MovieSummary[];
}

export interface TasteDnaResponse {
  selected_profiles: string[];
  coverage: FeatureCoverage;
  summary: {
    similarity_score: number | null;
    shared_rated_titles: number;
    metadata_coverage_ratio: number | null;
    tmdb_status: 'connected' | 'partial' | 'unavailable';
  };
  shared_signature: TasteTrait[];
  contrasts: TasteTrait[];
  dimensions: Partial<Record<TasteDimension, TasteTrait[]>>;
  semantic_neighbors?: Array<{
    movie: MovieSummary;
    reason: string;
    watched_by: string[];
    day_gap: number | null;
  }>;
}

export interface TasteTimelineProfilePoint {
  username: string;
  watch_events: number;
  unique_films: number;
  rated_events: number;
  average_rating: number | null;
  rewatch_count: number;
  liked_count: number;
}

export interface TasteTimelineTrait {
  dimension: 'genre' | 'director' | 'decade';
  label: string;
  watch_events: number;
  profile_count: number;
  average_rating: number | null;
}

export interface TasteTimelinePoint {
  key: string;
  label: string;
  year: number;
  season: string | null;
  watch_events: number;
  unique_films: number;
  rated_events: number;
  average_rating: number | null;
  rewatch_count: number;
  liked_count: number;
  per_profile: TasteTimelineProfilePoint[];
  top_traits: TasteTimelineTrait[];
}

export interface TasteTimelineResponse {
  selected_profiles: string[];
  filters: {
    dimensions: Array<'genre' | 'director' | 'decade'>;
    from_year: number | null;
    to_year: number | null;
  };
  coverage: FeatureCoverage;
  summary: {
    first_year: number | null;
    last_year: number | null;
    years: number;
    dated_watch_events: number;
    total_known_watches: number;
    undated_known_watches: number;
    date_coverage_ratio: number | null;
    rated_dated_events: number;
    rating_coverage_ratio: number | null;
  };
  yearly: TasteTimelinePoint[];
  seasonal: TasteTimelinePoint[];
}

export interface SignalCalendarBucket {
  date: string;
  signal_count: number;
  pair_hits: number;
  distinct_profiles: number;
  intensity: number;
}

export interface SignalCalendarResponse {
  selected_profiles: string[];
  gap_days: number;
  from: string;
  to: string;
  coverage: FeatureCoverage;
  buckets: SignalCalendarBucket[];
  events: Array<GroupSignalEvent & { event_id: string }>;
  monthly_summary: Array<{
    month: string;
    signal_count: number;
    pair_hits: number;
  }>;
}

export type WatchTogetherMode =
  | 'watchlist_overlap'
  | 'unseen_pick'
  | 'collective_blind_spots'
  | 'list_mission';

export interface PublicMovieList {
  id: number;
  name: string;
  owner: string;
  movie_count: number;
  is_ranked: boolean;
}

export interface PublicMovieListsResponse {
  selected_profiles: string[];
  summary: {
    available_lists: number;
    total_movie_items: number;
  };
  lists: PublicMovieList[];
}

export interface WatchProvider {
  id: number;
  name: string;
  logo_url: string | null;
  type: 'flatrate' | 'rent' | 'buy';
  regions: string[];
}

export interface WatchProviderRegionsResponse {
  default_region: string;
  worldwide_region: string;
  regions: Array<{
    code: string;
    movie_count: number;
  }>;
}

export interface WatchTogetherCandidate {
  movie: MovieSummary & {
    runtime_minutes: number | null;
    genres: string[];
    certification: string | null;
    providers: WatchProvider[];
  };
  on_watchlist_by: string[];
  watched_by: string[];
  unseen_by: string[];
  liked_by: string[];
  group_fit_score: number;
  reasons: string[];
  blind_spot_source?: {
    username: string;
    rating: number | null;
    liked: boolean;
  } | null;
  list_context?: {
    list_id: number;
    owner: string;
    name: string;
    position: number | null;
    notes: string | null;
  } | null;
}

export interface WatchTogetherResponse {
  selected_profiles: string[];
  mode: WatchTogetherMode;
  region: string;
  list_id?: number | null;
  selected_list?: PublicMovieList | null;
  available_lists?: PublicMovieList[];
  coverage: FeatureCoverage;
  summary: {
    candidates: number;
    on_every_watchlist: number;
    unseen_by_everyone: number;
    available_in_region: number;
  };
  recommendations: WatchTogetherCandidate[];
}

export type DataSurface =
  | 'profile_metadata'
  | 'ratings'
  | 'watch_events'
  | 'rewatches'
  | 'likes'
  | 'reviews'
  | 'tags'
  | 'watchlist'
  | 'lists'
  | 'tmdb';

export interface SurfaceCoverage {
  surface: DataSurface;
  status: 'complete' | 'partial' | 'missing' | 'stale';
  captured: number;
  expected: number | null;
  ratio: number | null;
  last_updated: string | null;
  warnings: string[];
}

export interface DataCoverageResponse {
  generated_at: string;
  overall_score: number;
  profiles: Array<{
    profile: ProfileRef;
    overall_score: number;
    surfaces: SurfaceCoverage[];
  }>;
  feature_readiness: Array<{
    feature: 'spy_signals' | 'pair_dossier' | 'signal_calendar' | 'watch_together' | 'list_mission' | 'taste_dna' | 'rewatch_echoes' | 'taste_timeline' | 'recent_changes';
    status: FeatureReadinessStatus;
    score: number;
    blockers: string[];
    warnings: string[];
  }>;
}

function selectedProfileParams(profiles: string[]): URLSearchParams {
  const params = new URLSearchParams();
  profiles.forEach((profile) => params.append('profiles', profile));
  return params;
}

export const insightsApi = {
  getPairDossier: async (profiles: string[], gapDays = 7): Promise<PairDossierResponse> => {
    const params = selectedProfileParams(profiles);
    params.set('gap_days', String(gapDays));
    const response = await api.get('/api/pair-dossier', { params });
    return response.data;
  },

  getTasteDna: async (profiles: string[]): Promise<TasteDnaResponse> => {
    const params = selectedProfileParams(profiles);
    params.set('dimensions', 'genre,director,actor,language,country,decade,keyword,runtime');
    const response = await api.get('/api/taste-dna', { params });
    return response.data;
  },

  getTasteTimeline: async (profiles: string[]): Promise<TasteTimelineResponse> => {
    const params = selectedProfileParams(profiles);
    const response = await api.get('/api/taste-timeline', { params });
    return response.data;
  },

  getSignalCalendar: async (
    profiles: string[],
    options: { gapDays: number; from: string; to: string },
  ): Promise<SignalCalendarResponse> => {
    const params = selectedProfileParams(profiles);
    params.set('gap_days', String(options.gapDays));
    params.set('from', options.from);
    params.set('to', options.to);
    const response = await api.get('/api/signal-calendar', { params });
    return response.data;
  },

  getWatchTogether: async (
    profiles: string[],
    options: {
      mode: WatchTogetherMode;
      region: string;
      maxRuntime?: number;
      genre?: string;
      availability?: string;
      listId?: number;
    },
  ): Promise<WatchTogetherResponse> => {
    const params = selectedProfileParams(profiles);
    params.set('mode', options.mode);
    params.set('region', options.region);
    params.set('limit', '30');
    if (options.maxRuntime) params.set('max_runtime', String(options.maxRuntime));
    if (options.genre) params.set('genre', options.genre);
    if (options.availability && options.availability !== 'all') {
      params.set('availability', options.availability);
    }
    if (options.listId) params.set('list_id', String(options.listId));
    const response = await api.get('/api/watch-together', { params });
    return response.data;
  },

  getPublicLists: async (profiles: string[]): Promise<PublicMovieListsResponse> => {
    const params = selectedProfileParams(profiles);
    const response = await api.get('/api/public-lists', { params });
    return response.data;
  },

  getWatchProviderRegions: async (): Promise<WatchProviderRegionsResponse> => {
    const response = await api.get('/api/watch-provider-regions');
    return response.data;
  },

  getDataCoverage: async (profiles: string[]): Promise<DataCoverageResponse> => {
    const params = selectedProfileParams(profiles);
    const response = await api.get('/api/data-coverage', { params });
    return response.data;
  },
};

export interface RecentChange {
  id: number;
  change_type: string;
  entity_type: string;
  detected_at: string | null;
  source_date?: string | null;
  source_kind: string;
  source_dataset?: string | null;
  username: string;
  movie: {
    id: number;
    title: string;
    year: number | null;
    poster_url: string | null;
  } | null;
  list: { id: number; name: string } | null;
  before: unknown;
  after: unknown;
}

export interface RecentChangesResponse {
  generated_at: string;
  scope: 'latest_sync' | 'history';
  changes: RecentChange[];
}

export const changesApi = {
  getRecentChanges: async (options: { profiles?: string[]; limit?: number; since?: string; latestSyncOnly?: boolean } = {}): Promise<RecentChangesResponse> => {
    const params = selectedProfileParams(options.profiles ?? []);
    params.set('limit', String(options.limit ?? 6));
    if (options.since) params.set('since', options.since);
    if (options.latestSyncOnly) params.set('latest_sync_only', 'true');
    const response = await api.get('/api/recent-changes', { params });
    return response.data;
  },
};

export default api;
