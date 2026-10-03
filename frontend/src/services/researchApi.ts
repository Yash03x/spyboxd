import api from './api';

export interface ResearchSummary {
  watches: number; films: number; rated: number; average_rating: number | null;
  rewatches: number; members: number; active_members: number;
  watches_per_member_30_days: number; low_rating_sample: boolean;
}
export interface ResearchRow {
  event_id: number; movie_id: number; title: string; year: number | null; username: string;
  groups: string[]; date: string; watched_date: string; logged_date: string | null;
  rating: number | null; rewatch: boolean; source_kind: string; film_url: string | null;
}
export interface ResearchOptions {
  from: string; to: string; basis: string; dimension: string; trait: string;
  q: string; sort: string; compareProfiles: string[]; offset?: number; limit?: number;
}
export interface ResearchResponse {
  period: { from: string; to: string; days: number; previous_from: string; previous_to: string; basis: string };
  groups: Array<{
    label: string; profiles: string[]; current: ResearchSummary; previous: ResearchSummary;
    change: { watches: number; watches_percent: number | null; rating: number | null };
    per_profile: Array<ResearchSummary & { username: string }>;
    monthly: Array<ResearchSummary & { month: string }>;
    traits: Array<ResearchSummary & { label: string }>;
  }>;
  evidence: { rows: ResearchRow[]; total: number; offset: number; limit: number };
  facets: string[];
  coverage: { status: string; undated_known_watches: number; warnings: string[] };
  method: string;
}
export interface RecommendationEvaluation {
  status: string; top_k: number; members_evaluated: number; members_selected: number;
  equal_member_mean: number | null; worst_member_mean: number | null; baseline_equal_member_mean: number | null;
  per_profile: Array<{ username: string; eligible_movies: number; evaluated: boolean;
    held_out_mean: number | null; mean_only_baseline: number | null; low_rated_picks: number; picks: number;
    examples: Array<{ movie_id: number; title: string; held_out_rating: number }> }>;
  method: string; limitations: string;
}

export async function getResearch(profiles: string[], options: ResearchOptions): Promise<ResearchResponse> {
  const params = new URLSearchParams();
  profiles.forEach((value) => params.append('profiles', value));
  options.compareProfiles.forEach((value) => params.append('compare_profiles', value));
  for (const key of ['from', 'to', 'basis', 'dimension', 'trait', 'q', 'sort'] as const) {
    if (options[key]) params.set(key, options[key]);
  }
  params.set('offset', String(options.offset ?? 0));
  params.set('limit', String(options.limit ?? 50));
  return (await api.get('/api/research', { params })).data;
}

export async function getRecommendationEvaluation(profiles: string[]): Promise<RecommendationEvaluation> {
  const params = new URLSearchParams();
  profiles.forEach((profile) => params.append('profiles', profile));
  return (await api.get('/api/recommendation-evaluation', { params })).data;
}
