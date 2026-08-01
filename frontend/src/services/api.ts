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
  /** Earliest diary entry we hold, derived from watch events, so it exists for
   *  every synced profile. `join_date` is the real answer but appears only in
   *  an account's own export, never on a public profile page. */
  first_logged_date?: string | null;
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
  letterboxd_username: string | null;
  primary_profile_status: 'tracked' | 'pending' | 'approved' | 'rejected' | 'available' | 'unlinked' | 'unconfigured';
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

export interface ProfileCatalogItem {
  id: number;
  username: string;
  display_name: string | null;
  profile_image_url: string | null;
  total_films: number;
  is_tracked: boolean;
}

export interface ProfileCatalogResponse {
  profiles: ProfileCatalogItem[];
  total: number;
  limit: number;
  offset: number;
}

export const authApi = {
  getCurrentUser: async (): Promise<CurrentUser> => {
    const response = await api.get('/api/me');
    return response.data;
  },
};

export interface ProfileExternalLink {
  label: string;
  url: string;
}

export interface ProfileFavoriteFilm {
  position: number;
  title: string;
  year: number | null;
  poster_url: string | null;
  letterboxd_url: string | null;
  /** Whether the film appears in this profile's own library at all. A stated
   *  favourite that was never logged is a different claim from a logged one. */
  in_library: boolean;
  /** Their own rating, or null when logged without one. */
  own_rating: number | null;
}

/**
 * Everything Letterboxd's own profile header shows, plus the Spyboxd-only
 * context beside it. Every observed field is nullable: the HTML scrape, the
 * RSS feed, and the official export each see a different subset, so `null`
 * means "not observed" and must render as nothing rather than an empty row.
 */
export interface ProfileHeader {
  username: string;
  display_name: string | null;
  bio: string | null;
  location: string | null;
  website: string | null;
  website_url: string | null;
  /** Every external link the member lists; Letterboxd allows more than one. */
  external_links?: ProfileExternalLink[];
  pronoun: string | null;
  member_badge: string | null;
  avatar_url: string | null;
  letterboxd_url: string;
  letterboxd_person_id: number | null;
  join_date: string | null;
  films_count: number | null;
  reviews_count: number | null;
  lists_count: number | null;
  watchlist_count: number | null;
  following_count: number | null;
  followers_count: number | null;
  films_this_year: number | null;
  favorites: ProfileFavoriteFilm[];
  synced_films: number | null;
  avg_rating: number | null;
  total_reviews: number | null;
  last_scraped_at: string | null;
  metadata_synced_at: string | null;
  /** Letterboxd's own /<user>/stats/ figures; key set varies by account. */
  stats_snapshot: Record<string, number | string> | null;
  stats_synced_at: string | null;
}

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
  profile_header?: ProfileHeader;
  rating_distribution: Record<string, number>;
  monthly_stats: ActivityData[];
  tag_counts?: TagCount[];
  recent_ratings: RecentRating[];
  recent_reviews: RecentReview[];
  recent_watching_trend: RecentWatchEvent[];
}

export interface TagCount {
  tag: string;
  count: number;
}

export interface RecentRating {
  movie_title: string;
  movie_year: number | null;
  rating: number | null;
  watched_date: string | null;
  is_rewatch: boolean;
  tags?: string[];
}

export interface RecentReview {
  movie_title: string;
  movie_year: number | null;
  rating: number | null;
  review_text: string | null;
  contains_spoilers: boolean;
  published_date: string | null;
  likes_count: number;
  tags?: string[];
}

export interface RecentWatchEvent {
  movie_title: string;
  movie_year: number | null;
  watched_date: string | null;
  rating: number | null;
  is_rewatch: boolean;
  tags?: string[];
}

export interface UploadFilesOptions {
  publish_owner_data?: boolean;
  require_full_sync?: boolean;
}

// Profile API endpoints
export const profileApi = {
  // Get all profiles
  getProfiles: async (): Promise<ProfileInfo[]> => {
    const response = await api.get('/profiles/');
    return response.data.profiles || [];
  },

  getTrackedProfiles: async (): Promise<ProfileInfo[]> => {
    const response = await api.get('/profiles/tracked');
    return response.data.profiles || [];
  },

  getCatalog: async (search?: string, limit = 100): Promise<ProfileCatalogResponse> => {
    const response = await api.get('/profiles/catalog', {
      params: {
        limit,
        ...(search?.trim() ? { search: search.trim() } : {}),
      },
    });
    return response.data;
  },

  trackExisting: async (profileId: number): Promise<{
    message: string;
    status: 'tracked';
    profile: ProfileRequestProfile;
  }> => {
    const response = await api.post(`/profiles/${profileId}/tracking`);
    return response.data;
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
    formData.append('require_full_sync', String(options.require_full_sync ?? false));
    
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

  getProfileSnapshot: async (username: string): Promise<ProfileInfo & {
    bio?: string | null;
    location?: string | null;
    website?: string | null;
  }> => {
    const response = await api.get(`/public/profile/${encodeURIComponent(username)}`);
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
  // Optional: cached snapshots produced before this field existed omit it.
  unique_movies?: number | null;
  average_rating: number | null;
  is_partial: boolean;
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

/**
 * The observed social link between two members of a co-watch, as annotated on
 * the event itself. Every direction is three-valued: `null` means no
 * authoritative following/followers import covers it, which is not the same as
 * an observed absence.
 *
 * `follows_earlier_watcher` is the strongest reading available — the later
 * watcher already followed the earlier one when these diary entries landed. It
 * is never evidence that one watch caused the other, and any copy built on it
 * must stay at "watched after someone they follow".
 */
export interface CoWatchFollowRelationship {
  a: string;
  b: string;
  a_follows_b: boolean | null;
  b_follows_a: boolean | null;
  mutual: boolean | null;
  /** Whether either direction was observable at all. */
  known: boolean;
  /** Whose own social import the reading is sourced from. */
  observed_by: string[];
  earlier_watcher: string | null;
  later_watcher: string | null;
  follows_earlier_watcher: boolean | null;
}

/** How much of a co-watch feed could be read against the follow graph. */
export interface CoWatchFollowGraphSummary {
  gap_events: number;
  follow_backed_gap_events: number;
  coincidental_gap_events: number;
  undetermined_gap_events: number;
  same_day_events: number;
  profiles_with_social_sync: string[];
  social_sync_coverage_ratio: number | null;
  warnings: string[];
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
  /**
   * Follow annotations. Optional because only the event feeds built from the
   * social-aware insights service carry them; a feed without them must render
   * exactly as it did before rather than as an absence of follows.
   */
  follow_relationship?: CoWatchFollowRelationship | null;
  follow_relationships?: CoWatchFollowRelationship[];
  follows_earlier_watcher?: boolean | null;
  /** True when any later watcher in the event already followed an earlier one. */
  follow_backed?: boolean | null;
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
  /** Social context for the echo; see `CoWatchFollowRelationship`. */
  follow_relationship?: CoWatchFollowRelationship | null;
  follows_earlier_watcher?: boolean | null;
  follow_backed?: boolean | null;
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
  /** Absent from responses produced before the echoes were read against follows. */
  follow_graph?: CoWatchFollowGraphSummary;
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

export interface PublicDashboardAnalytics {
  system_stats: Omit<SystemStats, 'last_updated'>;
  rating_distribution: Record<string, number>;
  activity_data: ActivityData[];
  signal_counts: {
    profiles_analyzed: number;
    profiles_with_diary_dates: number;
    shared_titles: number;
    same_day_events: number;
    one_day_gap_events: number;
    same_day_pair_hits: number;
    one_day_gap_pair_hits: number;
  };
  data_health: {
    active_profiles: number;
    completed_profiles: number;
    last_synced_at: string | null;
  };
  timestamp: string;
}

// Dashboard API endpoints
export const dashboardApi = {
  // Get dashboard analytics
  getAnalytics: async (scope: 'tracked' | 'global' = 'tracked'): Promise<DashboardAnalytics> => {
    const response = await api.get('/api/dashboard/analytics', { params: { scope } });
    return response.data;
  },
};

export const publicDashboardApi = {
  getAnalytics: async (): Promise<PublicDashboardAnalytics> => {
    const response = await api.get('/api/public/dashboard');
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
  letterboxd_url: string | null;
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
  contains_spoilers: boolean;
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
  /** Films watched in this trait. */
  sample_size: number;
  /** Films *rated* in this trait — the score is built from these alone, so a
   *  zero here means "no opinion", not "disliked". */
  rated_sample_size: number;
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
    /** Which date the points sit on; log dates only exist in account exports. */
    date_basis?: 'logged' | 'watched' | 'mixed';
    logged_date_events?: number;
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
    // `from`/`to` are optional on purpose. Sending a fixed window overrides the
    // backend's data-aware default, which anchors on the pair's own latest
    // event -- a pair whose newest activity predates the window then renders a
    // year of empty cells rather than the period they were actually active in.
    options: { gapDays: number; from?: string; to?: string },
  ): Promise<SignalCalendarResponse> => {
    const params = selectedProfileParams(profiles);
    params.set('gap_days', String(options.gapDays));
    if (options.from) params.set('from', options.from);
    if (options.to) params.set('to', options.to);
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

// Counterpart payload carried by follow-related recent changes
// (follow_added | follow_removed | follower_gained | follower_lost).
export interface FollowChangePayload {
  username: string;
  display_name: string | null;
  profile_url: string | null;
}

export type FollowGraphDirection = 'following' | 'followers' | 'both';

export interface FollowGraphEdge {
  direction: 'following' | 'follower';
  counterpart_username: string;
  counterpart_display_name: string | null;
  counterpart_avatar_url: string | null;
  counterpart_profile_url: string | null;
  position: number | null;
  is_imported_profile: boolean;
  counterpart_profile_id: number | null;
  removed_at: string | null;
}

export interface FollowGraphResponse {
  username: string;
  following_count: number | null;
  followers_count: number | null;
  edges: FollowGraphEdge[];
  total: number;
}

export interface FollowMutualPair {
  a: string;
  b: string;
  a_follows_b: boolean;
  b_follows_a: boolean;
  mutual: boolean;
}

export interface FollowMutualsResponse {
  profiles: string[];
  pairs: FollowMutualPair[];
  rollups: Record<string, { follows_in_group: number; followed_by_in_group: number }>;
}

export interface FollowSuggestion {
  username: string;
  display_name: string | null;
  avatar_url: string | null;
  followed_by: string[];
  followed_by_count: number;
  follows_back_count: number;
  already_imported: boolean;
  profile_id: number | null;
}

export interface FollowSuggestionsResponse {
  suggestions: FollowSuggestion[];
}

export const followGraphApi = {
  getFollowGraph: async (
    username: string,
    params: {
      direction?: FollowGraphDirection;
      includeRemoved?: boolean;
      limit?: number;
      offset?: number;
    } = {},
  ): Promise<FollowGraphResponse> => {
    const response = await api.get(`/api/profiles/${encodeURIComponent(username)}/follow-graph`, {
      params: {
        direction: params.direction ?? 'both',
        include_removed: params.includeRemoved ?? false,
        limit: params.limit ?? 100,
        offset: params.offset ?? 0,
      },
    });
    return response.data;
  },

  getMutuals: async (profiles: string[]): Promise<FollowMutualsResponse> => {
    const params = selectedProfileParams(profiles);
    const response = await api.get('/api/follow-graph/mutuals', { params });
    return response.data;
  },

  getSuggestions: async (options: { limit?: number; minOverlap?: number } = {}): Promise<FollowSuggestionsResponse> => {
    const response = await api.get('/api/follow-graph/suggestions', {
      params: {
        limit: options.limit ?? 20,
        min_overlap: options.minOverlap ?? 2,
      },
    });
    return response.data;
  },
};

export interface MemberContentLikeEntry {
  target_url: string;
  liked_date: string | null;
}

export interface MemberCommentEntry {
  target_url: string;
  commented_date: string | null;
  /** Server-parsed plain text; the API never ships raw comment markup. */
  comment_text: string | null;
}

export interface LostEntryRecord {
  lost_kind: 'deleted' | 'orphaned';
  entry_type: 'diary' | 'review' | 'comment' | 'list';
  title: string | null;
  release_year: number | null;
  source_url: string | null;
  entry_date: string | null;
  watched_date: string | null;
  rating: number | null;
  body_text: string | null;
}

export interface MemberArchiveResponse {
  username: string;
  liked_reviews: MemberContentLikeEntry[];
  liked_lists: MemberContentLikeEntry[];
  comments: MemberCommentEntry[];
  lost_entries: LostEntryRecord[];
  totals: {
    liked_reviews: number;
    liked_lists: number;
    comments: number;
    lost_entries: number;
  };
}

export const memberArchiveApi = {
  getArchive: async (username: string, limit = 100): Promise<MemberArchiveResponse> => {
    const response = await api.get(`/api/profiles/${encodeURIComponent(username)}/archive`, {
      params: { limit },
    });
    return response.data;
  },
};

/** How much of the profile the stats below could actually be computed from. */
export interface ProfileStatsCoverage {
  films_total: number;
  films_enriched: number;
  /** 0..1 share of synced films carrying TMDB metadata. */
  enrichment_ratio: number;
  dated_events: number;
  rated_films: number;
  reviews_total: number;
  /**
   * Reviews that resolved to a film in the library. Only these can place a
   * rating on either side of the reviewed/unreviewed split.
   */
  reviews_matched_to_films: number;
}

export interface ProfileStatsTotals {
  films: number;
  /** Null when no film in the profile has a known runtime. */
  hours_watched: number | null;
  /** 0..1 share of films that contributed runtime to `hours_watched`. */
  runtime_coverage: number;
  distinct_directors: number | null;
  distinct_actors: number | null;
  distinct_countries: number | null;
  distinct_languages: number | null;
  distinct_studios: number | null;
  longest_streak_weeks: number | null;
  multi_film_days: number | null;
  rewatches: number;
  average_rating: number | null;
}

export interface ProfileStatsPerson {
  name: string;
  count: number;
  /** Films in this bucket that carry a rating — the average's real denominator. */
  rated_count: number;
  average_rating: number | null;
}

export interface ProfileStatsBucket {
  label: string;
  count: number;
  /** Films in this bucket that carry a rating — the average's real denominator. */
  rated_count: number;
  average_rating: number | null;
}

export interface ProfileStatsCountryBucket extends ProfileStatsBucket {
  code: string | null;
}

/**
 * Buckets the API judged large enough to call a favourite. The server only
 * fills these once a bucket has at least three films, so `average_rating` is
 * always present here even though it is nullable in the plain buckets.
 */
export interface ProfileStatsHighestRated {
  /** `count` is every film in the bucket; `rated_count` is the average's denominator. */
  genre: { label: string; count: number; rated_count: number; average_rating: number } | null;
  decade: { label: string; count: number; rated_count: number; average_rating: number } | null;
  director: { name: string; count: number; rated_count: number; average_rating: number } | null;
}

export interface ProfileStatsRewatchedFilm {
  title: string;
  year: number | null;
  poster_url: string | null;
  letterboxd_url: string | null;
  /**
   * Watches as the diary holds them. A count of 1 beside a rewatch is real:
   * Letterboxd allows a rewatch flag when the original viewing was never
   * logged, and that missing viewing is not invented here.
   */
  watch_count: number;
  rating: number | null;
}

/**
 * What a profile returns to. `average_rating_rewatched` and
 * `average_rating_once` are two averages over two self-selected halves of the
 * same library — never a before-and-after of what rewatching does to a rating.
 */
export interface ProfileStatsRewatches {
  total_rewatches: number;
  films_rewatched: number;
  /** 0..1. Null for an empty library, which has no rate rather than a rate of zero. */
  rewatch_rate: number | null;
  most_rewatched: ProfileStatsRewatchedFilm[];
  average_rating_rewatched: number | null;
  average_rating_once: number | null;
}

export interface ProfileStatsLongestReview {
  title: string;
  year: number | null;
  length_chars: number;
}

export interface ProfileStatsLikedReview {
  title: string;
  year: number | null;
  likes_count: number;
  published_date: string | null;
}

/** Reviews published in a given calendar year; undated reviews belong to none. */
export interface ProfileStatsReviewYear {
  year: number;
  count: number;
}

/**
 * Writing habits. As with rewatches, the two averages describe which films get
 * written about, not what writing does to a rating.
 */
export interface ProfileStatsReviews {
  total_reviews: number;
  /** Reviews carrying prose; a rating logged bare has no length, not a length of 0. */
  with_text: number;
  spoiler_reviews: number;
  median_length_chars: number | null;
  longest: ProfileStatsLongestReview | null;
  most_liked: ProfileStatsLikedReview[];
  reviews_by_year: ProfileStatsReviewYear[];
  average_rating_reviewed: number | null;
  average_rating_unreviewed: number | null;
}

export interface ProfileStatsResponse {
  username: string;
  coverage: ProfileStatsCoverage;
  totals: ProfileStatsTotals;
  /** Rhythm rather than volume: the same film count reads differently if it
   *  arrived weekly or in two binges either side of a silence. */
  cadence: {
    active_days: number;
    span_days: number | null;
    days_per_active_week: number | null;
    weekday_counts: Record<string, number>;
    busiest_weekday: string | null;
    /** Only set when the silence is long enough to read as a stop, not a pause. */
    longest_dry_spell_days: number | null;
    dry_spell_started: string | null;
  };
  top_directors: ProfileStatsPerson[];
  /** Crew whose credits TMDB stores on most enriched films and nothing read
   *  until now: the people shaping what you watch without being counted. */
  top_composers: ProfileStatsPerson[];
  top_cinematographers: ProfileStatsPerson[];
  top_editors: ProfileStatsPerson[];
  director_gender: {
    /** Films with at least one director whose gender TMDB records. Films where
     *  none is recorded are excluded from the shares rather than assigned. */
    measured_films: number;
    women: number;
    men: number;
    mixed: number;
    women_share: number | null;
  };
  top_actors: ProfileStatsPerson[];
  top_studios: ProfileStatsPerson[];
  genres: ProfileStatsBucket[];
  countries: ProfileStatsCountryBucket[];
  languages: ProfileStatsBucket[];
  /** Ascending by decade, labelled like "1990s". */
  decades: ProfileStatsBucket[];
  highest_rated: ProfileStatsHighestRated;
  /**
   * Always present, even for a profile with neither: counts fall to zero and
   * every average, median and headline film falls to null, so the client can
   * say "none yet" instead of guessing whether the block failed to compute.
   */
  rewatches: ProfileStatsRewatches;
  /** A paired measurement, unlike the averages inside `rewatches`: the same
   *  person rating the same film on two separate viewings. */
  return_journeys: {
    revisited_films: number;
    median_days_to_return: number | null;
    rated_twice: number;
    rating_rose: number;
    rating_fell: number;
    rating_held: number;
    average_change: number | null;
  };
  reviews: ProfileStatsReviews;
  /**
   * Letterboxd's own stats-page figures, verbatim, for side-by-side
   * comparison. Null when that Patron-only page was never scraped, and the
   * key set varies by account, so read it defensively.
   */
  letterboxd_reported: Record<string, number | string | null> | null;
}

export const profileStatsApi = {
  getStats: async (username: string): Promise<ProfileStatsResponse> => {
    const response = await api.get(`/api/profiles/${encodeURIComponent(username)}/stats`);
    return response.data;
  },
};

/**
 * How much of the profile the rating comparison could actually be run over. A
 * film is only comparable once enough other tracked profiles have rated it, so
 * `compared_films` is always a subset of `rated_films`.
 */
export interface RatingComparisonCoverage {
  rated_films: number;
  compared_films: number;
  /** How many *other* profiles must have rated a film for it to count. */
  min_raters: number;
  /** Rated films carrying Letterboxd's own crowd average, the one external reference. */
  letterboxd_average_films: number;
}

/** Which way this profile leans against its own circle. */
export type RatingComparisonLean = 'generous' | 'harsh' | 'aligned';

export interface RatingComparisonSummary {
  /** Mean of (profile rating - group average). Null when nothing is comparable. */
  group_delta: number | null;
  /**
   * Mean of (profile rating - Letterboxd crowd average) over the rated films
   * that carry one. Null until the crowd-average backfill has reached them.
   */
  letterboxd_delta: number | null;
  lean: RatingComparisonLean | null;
  /** Pearson correlation of this profile's ratings against the group average. */
  agreement: number | null;
}

export interface RatingComparisonFilm {
  title: string;
  year: number | null;
  poster_url: string | null;
  letterboxd_url: string | null;
  profile_rating: number;
  group_average: number;
  /** profile_rating - group_average: positive means rated above the circle. */
  delta: number;
  rater_count: number;
  /** Letterboxd's crowd average, on the same five-point scale as every rating here. */
  letterboxd_average: number | null;
}

export interface RatingComparisonDivisiveFilm {
  title: string;
  year: number | null;
  poster_url: string | null;
  letterboxd_url: string | null;
  /** Widest gap between any two ratings of this film across all profiles. */
  rating_spread: number;
  /** Everyone who rated it — the spread's denominator, including this profile. */
  rater_count: number;
  /** The others only — the group average's denominator. */
  group_rater_count: number;
  /** Share of Letterboxd's crowd in the film's most popular half-star bucket.
   *  High means the wider world has largely settled, so a split here belongs to
   *  this circle rather than to the film. Null when no histogram is imported. */
  crowd_consensus: number | null;
  group_average: number;
  /** Null when this profile has not rated a film the rest of the group split over. */
  profile_rating: number | null;
}

export interface RatingComparisonResponse {
  username: string;
  coverage: RatingComparisonCoverage;
  summary: RatingComparisonSummary;
  most_generous: RatingComparisonFilm[];
  most_harsh: RatingComparisonFilm[];
  most_divisive: RatingComparisonDivisiveFilm[];
}

export const ratingComparisonApi = {
  getComparison: async (username: string, limit = 10): Promise<RatingComparisonResponse> => {
    const response = await api.get(
      `/api/profiles/${encodeURIComponent(username)}/rating-comparison`,
      { params: { limit } },
    );
    return response.data;
  },
};

/**
 * How much of the watchlist the queue below stands on. `watchlist_films` counts
 * only *unwatched* rows and is the denominator for everything else here, so a
 * client can say how much of the list the circle can actually speak to.
 */
export interface WatchlistInsightsCoverage {
  watchlist_films: number;
  /** Unwatched films at least one other tracked profile has rated. */
  rated_by_group: number;
  /** Unwatched films carrying Letterboxd's own crowd average. */
  with_letterboxd_average: number;
}

export interface WatchlistRater {
  username: string;
  rating: number;
}

export interface WatchlistRecommendation {
  title: string;
  year: number | null;
  poster_url: string | null;
  letterboxd_url: string | null;
  /** Averaged over *other* tracked profiles only — never this member's own rating. */
  group_average: number | null;
  group_raters: number;
  liked_by: number;
  letterboxd_average: number | null;
  /** Share of Letterboxd's crowd that rated it 4.5+ — how much room the film has
   *  to become a favourite. Null when no histogram has been imported, which is
   *  not the same as nobody rating it highly. */
  crowd_ceiling: number | null;
  /** Share that rated it 2.0 or below. */
  crowd_floor: number | null;
  /** Subscription services carrying it in the requested region. Empty means
   *  "not carried there", never "not streamable anywhere" — providers are only
   *  imported per country. */
  streaming_on?: string[];
  added_date: string | null;
  /** Null when the import carried no added date: an unknown wait, not a zero-day one. */
  days_waiting: number | null;
  /** Up to a handful of the members behind the average, best rating first. */
  raters: WatchlistRater[];
}

export interface WatchlistWaitingFilm {
  title: string;
  year: number | null;
  poster_url: string | null;
  letterboxd_url: string | null;
  added_date: string | null;
  days_waiting: number | null;
}

export interface WatchlistGenreCount {
  label: string;
  count: number;
}

export interface WatchlistInsightsResponse {
  username: string;
  coverage: WatchlistInsightsCoverage;
  recommendations: WatchlistRecommendation[];
  longest_waiting: WatchlistWaitingFilm[];
  genre_skew: WatchlistGenreCount[];
  totals: {
    /** Both read dated rows only; null when nothing on the list carried a date. */
    median_days_waiting: number | null;
    oldest_days_waiting: number | null;
  };
}

export const watchlistInsightsApi = {
  getInsights: async (username: string, limit = 20): Promise<WatchlistInsightsResponse> => {
    const response = await api.get(
      `/api/profiles/${encodeURIComponent(username)}/watchlist-insights`,
      { params: { limit } },
    );
    return response.data;
  },
};

/**
 * The rated films the obscurity index could be computed over. Films the
 * crowd-rating backfill has not reached are excluded rather than counted as an
 * audience of zero, so this pair is the caveat for the median.
 */
export interface ObscurityCoverage {
  rated_films: number;
  films_with_rating_count: number;
}

/** Which way this profile's audience sizes lean against the rest of the circle. */
export type ObscurityLean = 'obscure' | 'balanced' | 'mainstream';

export interface ObscurityIndex {
  /** Audience size of the typical rated film. A median: audience sizes are wildly skewed. */
  median_rating_count: number | null;
  mean_rating_count: number | null;
  /** 100 means every other tracked profile watches bigger films. Null with no one to compare to. */
  percentile_vs_group: number | null;
  /** Read straight off the percentile, so label and number can never disagree. */
  lean: ObscurityLean | null;
}

export interface ObscurityFilm {
  title: string;
  year: number | null;
  poster_url: string | null;
  letterboxd_url: string | null;
  rating_count: number | null;
  profile_rating: number;
}

export interface ObscurityCrowdPosition {
  title: string;
  year: number | null;
  poster_url: string | null;
  letterboxd_url: string | null;
  profile_rating: number;
  /** 0..1 share of the crowd's own histogram sitting at or below this rating. */
  share_at_or_below: number;
  crowd_average: number | null;
}

export interface ObscurityResponse {
  username: string;
  coverage: ObscurityCoverage;
  index: ObscurityIndex;
  most_obscure: ObscurityFilm[];
  most_mainstream: ObscurityFilm[];
  /** Empty — never null — until the rating-distribution backfill has been run. */
  crowd_position: ObscurityCrowdPosition[];
}

export const obscurityApi = {
  getObscurity: async (username: string, limit = 10): Promise<ObscurityResponse> => {
    const response = await api.get(
      `/api/profiles/${encodeURIComponent(username)}/obscurity`,
      { params: { limit } },
    );
    return response.data;
  },
};

export default api;
