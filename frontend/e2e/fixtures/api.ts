import type { Page, Route } from '@playwright/test';

const PROFILE_NAMES = [
  'alpha',
  'bravo',
  'charlie',
  'delta',
  'echo',
  'foxtrot',
  'golf',
  'hotel',
  'india',
  'juliet',
];

export const MISSING_POSTER_URL = 'https://assets.spyboxd.test/missing-poster.jpg';

/**
 * A follow graph with real edges, so the network view can be driven end to end.
 *
 * Deterministic rather than random: `alpha` is deliberately the busiest node so
 * a test can assert an ordering, and every pair is spelled out so a changed
 * rollup shows up as a diff rather than as arithmetic nobody re-checks.
 */
const FOLLOW_PAIRS: Array<[string, string, boolean, boolean]> = [
  // [a, b, a_follows_b, b_follows_a]
  ['alpha', 'bravo', true, true],
  ['alpha', 'charlie', true, true],
  ['alpha', 'delta', true, false],
  ['alpha', 'echo', false, true],
  ['bravo', 'charlie', true, true],
  ['bravo', 'delta', true, false],
  ['charlie', 'echo', false, true],
  ['delta', 'echo', true, true],
];

export const followMutuals = {
  profiles: ['alpha', 'bravo', 'charlie', 'delta', 'echo'],
  pairs: FOLLOW_PAIRS.map(([a, b, aFollowsB, bFollowsA]) => ({
    a,
    b,
    a_follows_b: aFollowsB,
    b_follows_a: bFollowsA,
    mutual: aFollowsB && bFollowsA,
  })),
  rollups: FOLLOW_PAIRS.reduce<
    Record<string, { follows_in_group: number; followed_by_in_group: number }>
  >((totals, [a, b, aFollowsB, bFollowsA]) => {
    totals[a] ??= { follows_in_group: 0, followed_by_in_group: 0 };
    totals[b] ??= { follows_in_group: 0, followed_by_in_group: 0 };
    if (aFollowsB) {
      totals[a].follows_in_group += 1;
      totals[b].followed_by_in_group += 1;
    }
    if (bFollowsA) {
      totals[b].follows_in_group += 1;
      totals[a].followed_by_in_group += 1;
    }
    return totals;
  }, {}),
};

export const profiles = PROFILE_NAMES.map((username, index) => ({
  username,
  display_name: username[0].toUpperCase() + username.slice(1),
  profile_image_url: null,
  avatar_url: null,
  total_films: 1_200 - index * 37,
  rated_films: 900 - index * 29,
  liked_films: 180 - index * 7,
  avg_rating: 3.4 + (index % 4) * 0.1,
  total_reviews: 80 - index * 3,
  // Export-only in reality; most profiles have none.
  join_date: index === 0 ? '2020-01-01' : null,
  first_logged_date: '2021-03-14',
  last_scraped_at: '2026-07-29T12:00:00Z',
  scraping_status: 'completed',
  data_coverage: {
    mode: 'full_sync',
    source: 'fixture',
    is_partial: false,
    summary: 'Full public data fixture.',
    limitations: [],
    stats_label: 'Full sync',
  },
}));

const readyCoverage = {
  status: 'ready',
  score: 100,
  dated_watch_events: 2_000,
  total_watch_events: 2_000,
  blockers: [],
  warnings: [],
  last_updated: '2026-07-29T12:00:00Z',
};

const sharedMovie = {
  title: 'Shared Fixture Film',
  year: 2024,
  profile_count: 2,
  profiles: ['alpha', 'bravo'],
  rating_count: 2,
  average_rating: 4.25,
  rating_stddev: 0.25,
  max_rating_gap: 0.5,
  liked_count: 2,
  rewatch_count: 0,
};

const pair = {
  profiles: ['alpha', 'bravo'],
  shared_titles: 42,
  same_day_count: 1,
  one_day_gap_count: 0,
  tight_window_count: 1,
  within_gap_count: 1,
  rating_overlap_count: 35,
  rating_correlation: 0.82,
  average_rating_gap: 0.3,
  alignment_score: 88,
  sample_titles: [{ title: 'Shared Fixture Film', year: 2024 }],
};

const signalEvent = {
  title: 'Shared Fixture Film',
  year: 2024,
  start_date: '2026-07-28',
  end_date: '2026-07-28',
  profile_count: 2,
  pair_count: 1,
  profiles: ['alpha', 'bravo'],
  participants: [
    { username: 'alpha', rating: 4.5, watched_date: '2026-07-28', is_rewatch: false },
    { username: 'bravo', rating: 4, watched_date: '2026-07-28', is_rewatch: false },
  ],
  average_rating: 4.25,
  max_rating_gap: 0.5,
  rewatch_count: 0,
  day_gap: 0,
};

// The pair's social link as the event feeds annotate it: bravo already followed
// alpha when these entries landed, which is what a follow marker may say and
// the ceiling of what it may claim.
const followRelationship = {
  a: 'alpha',
  b: 'bravo',
  a_follows_b: false,
  b_follows_a: true,
  mutual: false,
  known: true,
  observed_by: ['alpha', 'bravo'],
  earlier_watcher: 'alpha',
  later_watcher: 'bravo',
  follows_earlier_watcher: true,
};

// A gap event, so the follow marker has something to attach to. The same-day
// event above deliberately carries no annotation: with no later watcher there
// is nothing to say.
const gapSignalEvent = {
  title: 'Echoed Fixture Film',
  year: 2022,
  start_date: '2026-07-26',
  end_date: '2026-07-27',
  profile_count: 2,
  pair_count: 1,
  profiles: ['alpha', 'bravo'],
  participants: [
    { username: 'alpha', rating: 4, watched_date: '2026-07-26', is_rewatch: false },
    { username: 'bravo', rating: 3.5, watched_date: '2026-07-27', is_rewatch: false },
  ],
  average_rating: 3.75,
  max_rating_gap: 0.5,
  rewatch_count: 0,
  day_gap: 1,
  follow_relationship: followRelationship,
  follow_relationships: [followRelationship],
  follows_earlier_watcher: true,
  follow_backed: true,
};

const groupSignals = {
  summary: {
    profiles_analyzed: profiles.length,
    profiles_with_diary_dates: profiles.length,
    shared_titles: 42,
    same_day_events: 1,
    one_day_gap_events: 1,
    same_day_pair_hits: 1,
    one_day_gap_pair_hits: 1,
    gap_days: 1,
    gap_events: 2,
    gap_pair_hits: 2,
    most_shared_title: sharedMovie,
    strongest_alignment_pair: pair,
    most_divisive_title: sharedMovie,
  },
  same_day_events: [signalEvent],
  one_day_gap_events: [gapSignalEvent],
  gap_events: [signalEvent, gapSignalEvent],
  most_shared_titles: [sharedMovie],
  consensus_hits: [sharedMovie],
  divisive_titles: [sharedMovie],
  aligned_pairs: [pair],
  follow_paths: [],
};

const publicDashboard = {
  system_stats: {
    total_profiles: profiles.length,
    total_movies_tracked: 4_321,
    total_reviews: 680,
    global_avg_rating: 3.7,
  },
  rating_distribution: { '3.5': 120, '4.0': 240, '4.5': 80 },
  activity_data: [
    { month: '2026-05', movies_watched: 10, unique_movies: 8, average_rating: 3.7, is_partial: false },
    { month: '2026-06', movies_watched: 20, unique_movies: 16, average_rating: 3.8, is_partial: false },
    { month: '2026-07', movies_watched: 90, unique_movies: 70, average_rating: 3.9, is_partial: true },
  ],
  signal_counts: {
    profiles_analyzed: profiles.length,
    profiles_with_diary_dates: profiles.length,
    shared_titles: 42,
    same_day_events: 1,
    one_day_gap_events: 0,
    same_day_pair_hits: 1,
    one_day_gap_pair_hits: 0,
  },
  data_health: {
    active_profiles: profiles.length,
    completed_profiles: profiles.length,
    last_synced_at: '2026-07-29T12:00:00Z',
  },
  timestamp: '2026-07-29T12:00:00Z',
};

export const profileAnalysis = {
  username: 'alpha',
  total_films: 1_200,
  rated_films: 900,
  liked_films: 180,
  avg_rating: 3.7,
  total_reviews: 2,
  join_date: '2020-01-01',
  last_scraped_at: '2026-07-29T12:00:00Z',
  scraping_status: 'completed',
  enhanced_metrics: {},
  data_coverage: profiles[0].data_coverage,
  profile_header: {
    username: 'alpha',
    display_name: 'Alpha Viewer',
    bio: 'Fixture bio for the profile header.',
    location: 'Chennai',
    website: 'alpha.example.com',
    website_url: 'https://alpha.example.com',
    pronoun: 'they/them',
    member_badge: 'Patron',
    avatar_url: null,
    letterboxd_url: 'https://letterboxd.com/alpha/',
    letterboxd_person_id: 998877,
    join_date: '2020-01-01',
    films_count: 1_200,
    reviews_count: 2,
    lists_count: 4,
    watchlist_count: 310,
    following_count: 88,
    followers_count: 190,
    films_this_year: 120,
    favorites: [
      {
        position: 1,
        title: 'Favourite One',
        year: 1999,
        poster_url: null,
        letterboxd_url: 'https://letterboxd.com/film/favourite-one/',
        in_library: true,
        own_rating: 5,
      },
      {
        position: 2,
        title: 'Favourite Two',
        year: 2004,
        poster_url: null,
        letterboxd_url: 'https://letterboxd.com/film/favourite-two/',
        in_library: false,
        own_rating: null,
      },
    ],
    synced_films: 1_200,
    avg_rating: 3.7,
    total_reviews: 2,
    last_scraped_at: '2026-07-29T12:00:00Z',
    metadata_synced_at: '2026-07-29T12:00:00Z',
    stats_snapshot: { hours: 2_130, directors: 640, longest_streak: 19 },
    stats_synced_at: '2026-07-29T12:00:00Z',
  },
  rating_distribution: { '3.5': 120, '4.0': 240, '4.5': 80 },
  monthly_stats: [
    { month: '2026-05', movies_watched: 10, unique_movies: 8, average_rating: 3.7, is_partial: false },
    { month: '2026-06', movies_watched: 20, unique_movies: 16, average_rating: 3.8, is_partial: false },
    { month: '2026-07', movies_watched: 90, unique_movies: 70, average_rating: 3.9, is_partial: true },
  ],
  recent_watching_trend: Array.from({ length: 8 }, (_, index) => ({
    movie_title: `Recent Watch ${index + 1}`,
    movie_year: 2026,
    watched_date: `2026-07-${String(29 - index).padStart(2, '0')}`,
    rating: 4,
    is_rewatch: false,
  })),
  recent_ratings: Array.from({ length: 12 }, (_, index) => ({
    movie_title: `Recent Rating ${index + 1}`,
    movie_year: 2026,
    watched_date: null,
    rating: 3.5 + (index % 3) * 0.5,
    is_rewatch: false,
  })),
  recent_reviews: [
    {
      movie_title: 'Short Review',
      movie_year: 2026,
      rating: 4.5,
      review_text: 'A concise fixture review.',
      contains_spoilers: true,
      published_date: '2026-07-29',
      likes_count: 0,
    },
    {
      movie_title: 'Another Review',
      movie_year: 2026,
      rating: 4,
      review_text: 'A second concise fixture review.',
      contains_spoilers: false,
      published_date: '2026-07-28',
      likes_count: 0,
    },
  ],
};

export const profileStats = {
  username: 'alpha',
  coverage: {
    films_total: 1_200,
    films_enriched: 1_020,
    enrichment_ratio: 0.85,
    dated_events: 2_000,
    rated_films: 900,
    // Deliberately unequal, so the panel's "matched to a film" qualifier renders.
    reviews_total: 42,
    reviews_matched_to_films: 39,
  },
  totals: {
    films: 1_200,
    hours_watched: 2_118.5,
    runtime_coverage: 0.94,
    distinct_directors: 640,
    distinct_actors: 5_400,
    distinct_countries: 48,
    distinct_languages: 31,
    distinct_studios: 410,
    longest_streak_weeks: 17,
    multi_film_days: 88,
    rewatches: 64,
    average_rating: 3.72,
  },
  top_directors: [
    { name: 'Akira Kurosawa', count: 18, rated_count: 16, average_rating: 4.3 },
    { name: 'Agnès Varda', count: 12, rated_count: 10, average_rating: 4.1 },
    { name: 'Mani Ratnam', count: 9, rated_count: 7, average_rating: null },
  ],
  top_composers: [
    { name: 'Joe Hisaishi', count: 21, rated_count: 19, average_rating: 4.2 },
  ],
  top_cinematographers: [
    { name: 'Roger Deakins', count: 16, rated_count: 14, average_rating: 4.1 },
  ],
  top_editors: [
    { name: 'Thelma Schoonmaker', count: 11, rated_count: 9, average_rating: 4.0 },
  ],
  // Films where TMDB records no director gender are excluded from the split,
  // so measured_films is deliberately lower than the profile's film count.
  director_gender: { measured_films: 940, women: 96, men: 832, mixed: 12, women_share: 0.115 },
  top_actors: [
    { name: 'Toshiro Mifune', count: 14, rated_count: 12, average_rating: 4.2 },
    { name: 'Tilda Swinton', count: 11, rated_count: 9, average_rating: 3.9 },
  ],
  top_studios: [{ name: 'Studio Ghibli', count: 16, rated_count: 14, average_rating: 4.4 }],
  genres: [
    { label: 'Drama', count: 420, average_rating: 3.9 },
    { label: 'Comedy', count: 210, average_rating: 3.4 },
    { label: 'Horror', count: 95, average_rating: null },
  ],
  countries: [
    { label: 'United States', code: 'US', count: 520, average_rating: 3.6 },
    { label: 'Japan', code: 'JP', count: 180, average_rating: 4.1 },
    { label: 'India', code: null, count: 120, average_rating: 3.8 },
  ],
  languages: [
    { label: 'English', count: 700, average_rating: 3.6 },
    { label: 'Japanese', count: 160, average_rating: 4.1 },
  ],
  decades: [
    { label: '1970s', count: 90, average_rating: 4 },
    { label: '1980s', count: 140, average_rating: 3.8 },
    { label: '1990s', count: 260, average_rating: 3.9 },
    { label: '2000s', count: 310, average_rating: 3.6 },
  ],
  // `count` is the bucket; `rated_count` is what the average was built from.
  // They differ in real data, so the fixture makes them differ here too.
  highest_rated: {
    genre: { label: 'Documentary', count: 34, rated_count: 29, average_rating: 4.15 },
    decade: { label: '1970s', count: 90, rated_count: 71, average_rating: 4 },
    director: { name: 'Akira Kurosawa', count: 18, rated_count: 12, average_rating: 4.3 },
  },
  // Folded into the same panel. One rewatched film is unrated and one review
  // has no publication date, so both omission branches render.
  // Paired: the same person, the same film, two viewings. A much smaller set
  // than the revisit count, because both viewings have to carry a rating.
  return_journeys: {
    revisited_films: 12,
    median_days_to_return: 674,
    rated_twice: 12,
    rating_rose: 5,
    rating_fell: 1,
    rating_held: 6,
    average_change: 0.38,
  },
  rewatches: {
    total_rewatches: 64,
    films_rewatched: 41,
    rewatch_rate: 0.0341,
    most_rewatched: [
      {
        title: 'Rewatched Fixture Film',
        year: 2001,
        poster_url: null,
        letterboxd_url: 'https://letterboxd.com/film/rewatched-fixture-film/',
        watch_count: 5,
        rating: 4.5,
      },
      {
        title: 'Unrated Rewatch',
        year: null,
        poster_url: null,
        letterboxd_url: null,
        watch_count: 3,
        rating: null,
      },
    ],
    average_rating_rewatched: 4.12,
    average_rating_once: 3.65,
  },
  reviews: {
    total_reviews: 42,
    with_text: 38,
    spoiler_reviews: 6,
    median_length_chars: 640,
    longest: { title: 'Longest Fixture Review', year: 2015, length_chars: 4_210 },
    most_liked: [
      {
        title: 'Most Liked Fixture Review',
        year: 2018,
        likes_count: 96,
        published_date: '2026-03-14',
      },
      { title: 'Undated Fixture Review', year: null, likes_count: 12, published_date: null },
    ],
    reviews_by_year: [
      { year: 2024, count: 12 },
      { year: 2025, count: 18 },
      { year: 2026, count: 9 },
    ],
    average_rating_reviewed: 4.02,
    average_rating_unreviewed: 3.61,
  },
  // Deliberately overlaps our figures: `directors` agrees, `hours` and
  // `longest_streak` do not, so both comparison branches render.
  letterboxd_reported: { hours: 2_130, directors: 640, longest_streak: 19 },
};

// The unwatched watchlist ranked by the circle. One recommendation has no
// Letterboxd average and one waiting row has no added date, so both null
// branches render as omissions rather than zeros.
export const watchlistInsights = {
  username: 'alpha',
  coverage: {
    watchlist_films: 310,
    rated_by_group: 74,
    with_letterboxd_average: 268,
  },
  recommendations: [
    {
      title: 'Queued Fixture Film',
      year: 2016,
      poster_url: null,
      letterboxd_url: 'https://letterboxd.com/film/queued-fixture-film/',
      group_average: 4.42,
      group_raters: 4,
      liked_by: 3,
      letterboxd_average: 4.11,
      crowd_ceiling: 0.42,
      crowd_floor: 0.03,
      added_date: '2024-02-11',
      days_waiting: 871,
      raters: [
        { username: 'bravo', rating: 4.5 },
        { username: 'charlie', rating: 4.5 },
        { username: 'delta', rating: 4.5 },
        { username: 'echo', rating: 4 },
      ],
    },
    {
      title: 'Undated Queue Entry',
      year: null,
      poster_url: null,
      letterboxd_url: null,
      group_average: 4.25,
      group_raters: 2,
      liked_by: 0,
      letterboxd_average: null,
      added_date: null,
      days_waiting: null,
      raters: [
        { username: 'bravo', rating: 4.5 },
        { username: 'foxtrot', rating: 4 },
      ],
    },
  ],
  longest_waiting: [
    {
      title: 'Oldest Fixture Wait',
      year: 2009,
      poster_url: null,
      letterboxd_url: 'https://letterboxd.com/film/oldest-fixture-wait/',
      added_date: '2019-05-02',
      days_waiting: 2_646,
    },
    {
      title: 'Undated Fixture Wait',
      year: 2011,
      poster_url: null,
      letterboxd_url: null,
      added_date: null,
      days_waiting: null,
    },
  ],
  genre_skew: [
    { label: 'Drama', count: 96 },
    { label: 'Documentary', count: 41 },
    { label: 'Horror', count: 22 },
  ],
  totals: {
    median_days_waiting: 412,
    oldest_days_waiting: 2_646,
  },
};

// Audience size across the rated library. `crowd_position` is populated here,
// but the panel omits that section entirely when the backfill has not run.
export const obscurity = {
  username: 'alpha',
  coverage: {
    rated_films: 900,
    films_with_rating_count: 742,
  },
  index: {
    median_rating_count: 12_480,
    mean_rating_count: 240_115,
    percentile_vs_group: 78.5,
    lean: 'obscure',
  },
  most_obscure: [
    {
      title: 'Obscure Fixture Film',
      year: 1978,
      poster_url: null,
      letterboxd_url: 'https://letterboxd.com/film/obscure-fixture-film/',
      rating_count: 205,
      profile_rating: 4,
    },
    {
      title: 'Second Obscure Fixture',
      year: 1985,
      poster_url: null,
      letterboxd_url: null,
      rating_count: 613,
      profile_rating: 3.5,
    },
  ],
  most_mainstream: [
    {
      title: 'Mainstream Fixture Film',
      year: 2014,
      poster_url: null,
      letterboxd_url: 'https://letterboxd.com/film/mainstream-fixture-film/',
      rating_count: 6_110_855,
      profile_rating: 4.5,
    },
  ],
  // Where they usually land, plus the opposite tail: somebody can be out on a
  // limb in both directions at once.
  crowd_percentile: { measured_films: 706, typical_share: 0.653, lean: 'generous' },
  crowd_position_below: [
    {
      title: 'Adored By Everyone Else',
      year: 2018,
      poster_url: null,
      letterboxd_url: 'https://letterboxd.com/film/adored-by-everyone-else/',
      profile_rating: 5,
      share_at_or_below: 0.9714,
      crowd_average: 3.11,
    },
  ],
  crowd_position: [
    {
      title: 'Contrarian Fixture Film',
      year: 2019,
      poster_url: null,
      letterboxd_url: 'https://letterboxd.com/film/contrarian-fixture-film/',
      profile_rating: 2,
      share_at_or_below: 0.0412,
      crowd_average: 4.03,
    },
    {
      title: 'Unaveraged Crowd Fixture',
      year: 2020,
      poster_url: null,
      letterboxd_url: null,
      profile_rating: 5,
      share_at_or_below: 0.9821,
      crowd_average: null,
    },
  ],
};

// Ratings against the rest of the tracked circle. Deliberately mixed: one
// champion without a Letterboxd crowd average and one divisive film this
// profile never rated, so both omission branches render.
export const ratingComparison = {
  username: 'alpha',
  coverage: {
    rated_films: 900,
    compared_films: 312,
    min_raters: 2,
    letterboxd_average_films: 268,
  },
  summary: {
    group_delta: 0.31,
    letterboxd_delta: -0.12,
    lean: 'generous',
    agreement: 0.62,
  },
  most_generous: [
    {
      title: 'Champion Fixture Film',
      year: 2019,
      poster_url: null,
      letterboxd_url: 'https://letterboxd.com/film/champion-fixture-film/',
      profile_rating: 4.5,
      group_average: 2.75,
      delta: 1.75,
      rater_count: 4,
      letterboxd_average: 3.21,
      crowd_ceiling: 0.42,
      crowd_floor: 0.03,
    },
    {
      title: 'Unenriched Champion',
      year: null,
      poster_url: null,
      letterboxd_url: null,
      profile_rating: 5,
      group_average: 3.5,
      delta: 1.5,
      rater_count: 3,
      letterboxd_average: null,
    },
  ],
  most_harsh: [
    {
      title: 'Panned Fixture Film',
      year: 2021,
      poster_url: null,
      letterboxd_url: 'https://letterboxd.com/film/panned-fixture-film/',
      profile_rating: 1.5,
      group_average: 3.83,
      delta: -2.33,
      rater_count: 5,
      letterboxd_average: 3.94,
      crowd_ceiling: 0.42,
      crowd_floor: 0.03,
    },
  ],
  most_divisive: [
    {
      title: 'Divisive Fixture Film',
      year: 2017,
      poster_url: null,
      letterboxd_url: 'https://letterboxd.com/film/divisive-fixture-film/',
      rating_spread: 3,
      rater_count: 6,
      group_rater_count: 5,
      crowd_consensus: 0.41,
      group_average: 3.08,
      profile_rating: 4.5,
    },
    {
      title: 'Unrated Divisive Fixture',
      year: 2013,
      poster_url: null,
      letterboxd_url: null,
      rating_spread: 2.5,
      rater_count: 4,
      group_rater_count: 3,
      crowd_consensus: 0.41,
      group_average: 2.88,
      profile_rating: null,
    },
  ],
};

const dataCoverage = {
  generated_at: '2026-07-29T12:00:00Z',
  overall_score: 100,
  profiles: profiles.slice(0, 8).map((profile) => ({
    profile: {
      username: profile.username,
      display_name: profile.display_name,
      avatar_url: null,
      total_films: profile.total_films,
    },
    overall_score: 100,
    surfaces: [],
  })),
  feature_readiness: [
    'spy_signals',
    'pair_dossier',
    'signal_calendar',
    'watch_together',
    'list_mission',
    'taste_dna',
    'rewatch_echoes',
    'taste_timeline',
    'recent_changes',
  ].map((feature) => ({ feature, status: 'ready', score: 100, blockers: [], warnings: [] })),
};

const pairDossier = {
  selected_profiles: ['alpha', 'bravo'],
  coverage: readyCoverage,
  summary: {
    shared_titles: 42,
    rated_overlap: 35,
    same_day_events: 1,
    within_gap_events: 1,
    alignment_score: 88,
    rating_correlation: 0.82,
    average_rating_gap: 0.3,
    directional_leader: null,
    date_coverage_ratio: 1,
  },
  co_watches: [signalEvent],
  influence_paths: [],
  agreements: [
    {
      movie: {
        movie_id: 147_509,
        tmdb_id: 206_487,
        letterboxd_slug: 'predestination',
        letterboxd_url: 'https://letterboxd.com/film/predestination/',
        title: 'Predestination',
        year: 2014,
        poster_url: null,
      },
      observations: [
        {
          username: 'alpha',
          rating: 5,
          watched_dates: ['2023-06-19'],
          liked: true,
          rewatch_count: 0,
          review_text: 'The identity loop changes how every earlier scene reads.',
          review_date: '2023-06-19',
          contains_spoilers: true,
        },
        {
          username: 'bravo',
          rating: 5,
          watched_dates: ['2023-06-19'],
          liked: false,
          rewatch_count: 0,
          review_text: null,
          review_date: null,
          contains_spoilers: false,
        },
      ],
      rating_gap: 0,
      minimum_watch_gap_days: 0,
    },
  ],
  disagreements: [],
  monthly_alignment: [],
};

const watchTogether = {
  selected_profiles: profiles.slice(0, 4).map((profile) => profile.username),
  mode: 'unseen_pick',
  region: 'ALL',
  coverage: readyCoverage,
  summary: {
    candidates: 1,
    on_every_watchlist: 0,
    unseen_by_everyone: 1,
    available_in_region: 1,
  },
  recommendations: [
    {
      movie: {
        movie_id: 99,
        tmdb_id: 550,
        letterboxd_slug: 'fallback-fixture',
        letterboxd_url: 'https://example.com/film/not-the-fixture/',
        title: 'Fallback Fixture',
        year: 2024,
        poster_url: MISSING_POSTER_URL,
        runtime_minutes: 101,
        genres: ['Drama'],
        certification: 'PG-13',
        providers: [
          { id: 8, name: 'Fixture Stream', logo_url: null, type: 'flatrate', regions: ['DE', 'GB'] },
        ],
      },
      on_watchlist_by: ['alpha', 'bravo'],
      watched_by: [],
      unseen_by: ['alpha', 'bravo', 'charlie', 'delta'],
      liked_by: [],
      group_fit_score: 91,
      reasons: ['On 2 selected watchlists', 'Unseen by everyone selected'],
      blind_spot_source: null,
      list_context: null,
    },
  ],
};

function json(route: Route, body: unknown) {
  return route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
}

interface ApiFixtureState {
  profiles: typeof profiles;
  currentUser: {
    user_id: string;
    is_admin: boolean;
    letterboxd_username: string | null;
    primary_profile_status: 'tracked' | 'pending' | 'approved' | 'rejected' | 'available' | 'unlinked' | 'unconfigured';
  };
  requests: Array<{
    id: number;
    requester_user_id: string;
    requested_username: string;
    status: 'pending' | 'approved' | 'rejected' | 'fulfilled';
    note: string | null;
    requested_at: string;
    updated_at: string;
    resolved_at: string | null;
    resolved_by_user_id: string | null;
    profile: null;
  }>;
}

async function handleApiRoute(route: Route, state: ApiFixtureState, isAdmin: boolean) {
  const url = new URL(route.request().url());
  const path = url.pathname.replace(/\/$/, '') || '/';
  const method = route.request().method();

  if (path === '/api/public/dashboard' && method === 'GET') {
    return json(route, publicDashboard);
  }

  if (route.request().headers().authorization !== 'Bearer e2e-token') {
    return route.fulfill({
      status: 401,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Missing fixture bearer token' }),
    });
  }

  if (path === '/api/me') return json(route, state.currentUser);
  if (path === '/upload' && method === 'POST') {
    return json(route, {
      loaded_profiles: ['alpha', 'bravo'],
      imports: [
        { username: 'alpha', source_kind: 'full_html_upload', movies_loaded: 1_200 },
        { username: 'bravo', source_kind: 'full_html_upload', movies_loaded: 1_163 },
      ],
      errors: [],
    });
  }
  if (path === '/profiles' && method === 'GET') return json(route, { profiles: state.profiles });
  if (path === '/profiles/tracked' && method === 'GET') return json(route, { profiles: state.profiles });
  const analysisMatch = path.match(/^\/profiles\/([^/]+)\/analysis$/);
  if (analysisMatch && method === 'GET') {
    return json(route, {
      ...profileAnalysis,
      username: decodeURIComponent(analysisMatch[1]),
    });
  }
  if (path === '/profiles/catalog' && method === 'GET') {
    const search = (url.searchParams.get('search') ?? '').trim().toLowerCase();
    const limit = Number(url.searchParams.get('limit') ?? 100);
    const offset = Number(url.searchParams.get('offset') ?? 0);
    const matchingProfiles = profiles
      .map((profile, index) => ({ profile, id: index + 1 }))
      .filter(({ profile }) => !search
        || profile.username.toLowerCase().includes(search)
        || (profile.display_name ?? '').toLowerCase().includes(search));
    return json(route, {
      profiles: matchingProfiles.slice(offset, offset + limit).map(({ profile, id }) => ({
        id,
        username: profile.username,
        display_name: profile.display_name,
        profile_image_url: profile.profile_image_url,
        total_films: profile.total_films,
        is_tracked: state.profiles.some((tracked) => tracked.username === profile.username),
      })),
      total: matchingProfiles.length,
      limit,
      offset,
    });
  }
  const trackMatch = path.match(/^\/profiles\/(\d+)\/tracking$/);
  if (trackMatch && method === 'POST') {
    const profile = profiles[Number(trackMatch[1]) - 1];
    if (!profile) return route.fulfill({ status: 404, body: '' });
    if (!state.profiles.some((tracked) => tracked.username === profile.username)) {
      state.profiles.push({ ...profile });
    }
    return json(route, {
      message: `${profile.username} is now monitored.`,
      status: 'tracked',
      profile: { ...profile, id: Number(trackMatch[1]), is_active: true },
    });
  }
  if (path === '/profiles/requests' && method === 'GET') return json(route, { requests: state.requests });
  if (path === '/profiles/requests' && method === 'POST') {
    const payload = route.request().postDataJSON() as { username: string };
    const username = payload.username.toLowerCase();
    const existing = state.profiles.find((profile) => profile.username === username);
    if (existing) {
      return json(route, {
        message: 'Profile added to your tracked profiles.',
        status: 'tracked',
        profile: { ...existing, id: 1, is_active: true },
        request: null,
      });
    }
    const request = {
      id: state.requests.length + 1,
      requester_user_id: 'user_e2e',
      requested_username: username,
      status: 'pending' as const,
      note: null,
      requested_at: '2026-07-30T12:00:00Z',
      updated_at: '2026-07-30T12:00:00Z',
      resolved_at: null,
      resolved_by_user_id: null,
      profile: null,
    };
    state.requests.unshift(request);
    return json(route, {
      message: 'Profile request submitted.',
      status: 'pending',
      profile: null,
      request,
    });
  }
  const untrackMatch = path.match(/^\/profiles\/([^/]+)\/tracking$/);
  if (untrackMatch && method === 'DELETE') {
    const username = decodeURIComponent(untrackMatch[1]);
    state.profiles = state.profiles.filter((profile) => profile.username !== username);
    return json(route, { message: 'Profile removed from your tracked profiles.', status: 'untracked', username });
  }
  const deleteProfileMatch = path.match(/^\/profiles\/([^/]+)$/);
  if (deleteProfileMatch && method === 'DELETE') {
    return json(route, { message: `${decodeURIComponent(deleteProfileMatch[1])} deleted.` });
  }
  if (path === '/admin/profile-requests' && method === 'GET') return json(route, { requests: isAdmin ? state.requests : [] });
  if (path === '/api/dashboard/analytics') {
    return json(route, {
      system_stats: {
        total_profiles: profiles.length,
        total_movies_tracked: 4_321,
        total_reviews: 680,
        global_avg_rating: 3.7,
        last_updated: '2026-07-29T12:00:00Z',
      },
      top_rated_movies: [],
      rating_distribution: { '3.5': 120, '4.0': 240, '4.5': 80 },
      activity_data: [
        { month: '2026-05', movies_watched: 10, unique_movies: 8, average_rating: 3.7, is_partial: false },
        { month: '2026-06', movies_watched: 20, unique_movies: 16, average_rating: 3.8, is_partial: false },
        { month: '2026-07', movies_watched: 90, unique_movies: 70, average_rating: 3.9, is_partial: true },
      ],
      group_signals: groupSignals,
      timestamp: '2026-07-29T12:00:00Z',
    });
  }
  if (path === '/api/recent-changes') {
    // Carries entries: an empty list disables the Investigate control, so the
    // hand-off it performs was never exercised.
    return json(route, {
      generated_at: '2026-07-29T12:00:00Z',
      scope: 'latest_sync',
      changes: [
        {
          id: 1,
          change_type: 'review_added',
          entity_type: 'review',
          detected_at: '2026-07-29T11:00:00Z',
          source_date: '2026-07-28',
          source_kind: 'full_html_upload',
          source_dataset: 'reviews',
          username: profiles[1].username,
          movie: { id: 501, title: 'Fixture Film', year: 2024, poster_url: null },
          list: null,
          before: null,
          after: null,
        },
      ],
    });
  }
  if (path === '/api/spy-signals') {
    const selected = url.searchParams.getAll('profiles');
    return json(route, {
      selected_profiles: selected.length > 0 ? selected : profiles.map((profile) => profile.username),
      gap_days: Number(url.searchParams.get('gap_days') ?? 1),
      group_signals: groupSignals,
    });
  }
  if (path === '/api/rewatch-echoes') {
    return json(route, {
      selected_profiles: url.searchParams.getAll('profiles'),
      gap_days: Number(url.searchParams.get('gap_days') ?? 1),
      coverage: readyCoverage,
      summary: {
        echoes: 1,
        movies: 1,
        same_day: 0,
        within_gap: 1,
        first_known_plus_rewatch: 1,
        rewatch_plus_rewatch: 0,
        date_coverage_ratio: 1,
      },
      follow_graph: {
        gap_events: 1,
        follow_backed_gap_events: 1,
        coincidental_gap_events: 0,
        undetermined_gap_events: 0,
        same_day_events: 0,
        profiles_with_social_sync: ['alpha', 'bravo'],
        social_sync_coverage_ratio: 1,
        warnings: [
          'A follow edge is an observed social link, not evidence that one member\'s watch caused another\'s.',
        ],
      },
      echoes: [
        {
          echo_id: 'echo0000fixture1',
          movie: {
            movie_id: 4_242,
            tmdb_id: null,
            letterboxd_slug: 'echoed-fixture-film',
            letterboxd_url: 'https://letterboxd.com/film/echoed-fixture-film/',
            title: 'Echoed Fixture Film',
            year: 2022,
            poster_url: null,
          },
          pattern: 'first_known_plus_rewatch',
          timing: 'within_gap',
          start_date: '2026-07-26',
          end_date: '2026-07-27',
          day_gap: 1,
          participants: [
            {
              username: 'alpha',
              rating: 4,
              watched_date: '2026-07-26',
              is_rewatch: true,
              liked: true,
              watch_kind: 'rewatch',
              classification_basis: 'letterboxd_rewatch_flag',
              timing_role: 'leader',
            },
            {
              username: 'bravo',
              rating: 3.5,
              watched_date: '2026-07-27',
              is_rewatch: false,
              liked: false,
              watch_kind: 'first_known_watch',
              classification_basis: 'earliest_observed_unmarked_event',
              timing_role: 'follower',
            },
          ],
          follow_relationship: followRelationship,
          follows_earlier_watcher: true,
          follow_backed: true,
        },
      ],
    });
  }
  if (path === '/api/data-coverage') return json(route, dataCoverage);
  if (path === '/api/pair-dossier') return json(route, pairDossier);
  if (path === '/api/watch-provider-regions') {
    return json(route, {
      default_region: 'ALL',
      worldwide_region: 'ALL',
      regions: [
        { code: 'DE', movie_count: 100 },
        { code: 'GB', movie_count: 90 },
        { code: 'IN', movie_count: 80 },
        { code: 'US', movie_count: 110 },
      ],
    });
  }
  if (path === '/api/watch-together') return json(route, watchTogether);

  // Single-profile taste panel on Analysis; contract-shaped so the page
  // renders without console noise.
  if (path === '/api/taste-dna') {
    return json(route, {
      selected_profiles: [profiles[0].username],
      dimensions: {
        genre: [
          {
            id: 'genre:drama',
            label: 'Drama',
            dimension: 'genre',
            group_score: 78,
            sample_size: 42,
            average_rating: 3.9,
            like_rate: 0.3,
            watch_share: 1,
            per_profile: [
              // `sample_size` is films watched, `rated_sample_size` films rated; they
              // differ in real data and the score is built from the latter.
              { username: profiles[0].username, score: 78, sample_size: 42, rated_sample_size: 35, average_rating: 3.9 },
            ],
            top_movies: [],
          },
        ],
      },
      // The real endpoint always returns this block, and the panel reads
      // `summary.similarity_score` unguarded. Omitting it here threw
      // "Cannot read properties of undefined" and took the whole tab down,
      // which is why nothing under it was ever exercised.
      summary: {
        similarity_score: 72.5,
        shared_rated_titles: 35,
        metadata_coverage_ratio: 0.92,
        tmdb_status: 'connected',
      },
      shared_signature: [],
      contrasts: [],
      // Carries entries on purpose. The backend returned a hard-coded empty
      // list from the first commit, and because the fixture omitted the field
      // too, nothing ever noticed the panel was permanently blank.
      semantic_neighbors: [
        {
          movie: { movie_id: 501, title: 'Decision to Leave', release_year: 2022, poster_url: null },
          reason: 'Both watched a Park Chan-wook film',
          watched_by: [profiles[0].username, profiles[1].username],
          day_gap: 2,
        },
        {
          movie: { movie_id: 502, title: 'Fallen Angels', release_year: 1995, poster_url: null },
          reason: 'Both watched a Wong Kar-Wai film',
          watched_by: [profiles[1].username, profiles[0].username],
          day_gap: 3,
        },
      ],
      coverage: { status: 'ready', score: 100, blockers: [], warnings: [] },
    });
  }

  // Social graph. The mutuals fixture carries real edges: an empty graph
  // renders "no follow connections" and leaves every node, the ego view and the
  // deep-dive hand-off untestable, which is how a blank-on-back regression
  // reached production unnoticed.
  if (path === '/api/follow-graph/suggestions') return json(route, { suggestions: [] });
  if (path === '/api/follow-graph/mutuals') {
    return json(route, followMutuals);
  }
  {
    // Patron-only stats, computed for everyone. Contract-shaped so the
    // Analysis panel renders (and its Letterboxd comparison fires) without
    // console noise from an unmocked request.
    const statsMatch = path.match(/^\/api\/profiles\/([^/]+)\/stats$/);
    if (statsMatch) {
      return json(route, { ...profileStats, username: decodeURIComponent(statsMatch[1]) });
    }
  }
  {
    // Rating comparison against the tracked circle. Contract-shaped so the
    // Analysis panel renders instead of 404-ing into a console error.
    const comparisonMatch = path.match(/^\/api\/profiles\/([^/]+)\/rating-comparison$/);
    if (comparisonMatch) {
      return json(route, {
        ...ratingComparison,
        username: decodeURIComponent(comparisonMatch[1]),
      });
    }
  }
  {
    // The unwatched watchlist ranked by the circle, and how mainstream the
    // rated library is. Both are Analysis panels, so an unmocked request would
    // 404 into the smoke suite's console-error assertion.
    const watchlistMatch = path.match(/^\/api\/profiles\/([^/]+)\/watchlist-insights$/);
    if (watchlistMatch) {
      return json(route, {
        ...watchlistInsights,
        username: decodeURIComponent(watchlistMatch[1]),
      });
    }
    const obscurityMatch = path.match(/^\/api\/profiles\/([^/]+)\/obscurity$/);
    if (obscurityMatch) {
      return json(route, { ...obscurity, username: decodeURIComponent(obscurityMatch[1]) });
    }
  }
  {
    const archiveMatch = path.match(/^\/api\/profiles\/([^/]+)\/archive$/);
    if (archiveMatch) {
      return json(route, {
        username: decodeURIComponent(archiveMatch[1]),
        liked_reviews: [],
        liked_lists: [],
        comments: [],
        lost_entries: [],
        totals: { liked_reviews: 0, liked_lists: 0, comments: 0, lost_entries: 0 },
      });
    }
  }
  {
    const followGraphMatch = path.match(/^\/api\/profiles\/([^/]+)\/follow-graph$/);
    if (followGraphMatch) {
      return json(route, {
        username: decodeURIComponent(followGraphMatch[1]),
        following_count: null,
        followers_count: null,
        edges: [],
        total: 0,
      });
    }
  }

  return route.fulfill({
    status: 404,
    contentType: 'application/json',
    body: JSON.stringify({ detail: `No e2e fixture for ${path}` }),
  });
}

export async function installApiMocks(
  page: Page,
  options: {
    authenticated?: boolean;
    isAdmin?: boolean;
    profileCount?: number;
    letterboxdUsername?: string | null;
    primaryProfileStatus?: ApiFixtureState['currentUser']['primary_profile_status'];
  } = {},
) {
  const authenticated = options.authenticated ?? true;
  const isAdmin = options.isAdmin ?? false;
  const letterboxdUsername = options.letterboxdUsername === undefined
    ? 'letterboxd_user'
    : options.letterboxdUsername;

  if (authenticated) {
    await page.context().addCookies([{
      name: 'spyboxd-e2e-auth',
      value: '1',
      domain: 'localhost',
      path: '/',
    }]);
  }

  await page.addInitScript(({ signedIn, username }) => {
    const effectiveSignedIn = signedIn && document.cookie.split(';').some((cookie) => (
      cookie.trim() === 'spyboxd-e2e-auth=1'
    ));
    const user = effectiveSignedIn ? {
      id: 'user_e2e',
      firstName: 'E2E',
      lastName: 'User',
      fullName: 'E2E User',
      username,
      imageUrl: '',
      hasImage: false,
      organizationMemberships: [],
    } : null;
    const session = effectiveSignedIn ? {
      id: 'sess_e2e',
      status: 'active',
      user,
      factorVerificationAge: null,
      actor: null,
      lastActiveToken: { jwt: { claims: { sub: 'user_e2e', sid: 'sess_e2e', letterboxd_username: username } } },
      getToken: async () => 'e2e-token',
    } : null;
    const resources = {
      client: { sessions: session ? [session] : [] },
      session,
      user,
      organization: null,
    };
    const statusListeners = new Set<(status: string) => void>();
    const clerk = {
      loaded: true,
      status: 'ready',
      isSignedIn: effectiveSignedIn,
      client: resources.client,
      session: resources.session,
      user: resources.user,
      organization: resources.organization,
      __internal_lastEmittedResources: resources,
      __internal_updateProps: async () => undefined,
      addListener(listener: (state: typeof resources) => void, options?: { skipInitialEmit?: boolean }) {
        if (!options?.skipInitialEmit) listener(resources);
        return () => undefined;
      },
      on(event: string, listener: (value: string) => void, options?: { notify?: boolean }) {
        if (event === 'status') {
          statusListeners.add(listener);
          if (options?.notify) queueMicrotask(() => listener('ready'));
        }
        return () => statusListeners.delete(listener);
      },
      off(event: string, listener: (value: string) => void) {
        if (event === 'status') statusListeners.delete(listener);
      },
      buildSignInUrl: () => '/sign-in',
      buildSignUpUrl: () => '/sign-up',
      buildAfterSignOutUrl: () => '/',
      openSignIn: () => undefined,
      load: async () => undefined,
      signOut: async (options?: { redirectUrl?: string }) => {
        document.cookie = 'spyboxd-e2e-auth=; Max-Age=0; Path=/; SameSite=Lax';
        document.cookie = 'spyboxd-e2e-auth=; Max-Age=0; Path=/; Domain=localhost; SameSite=Lax';
        window.location.assign(options?.redirectUrl ?? '/');
      },
      mountUserButton(node: HTMLElement) {
        const button = document.createElement('button');
        button.type = 'button';
        button.setAttribute('aria-label', 'Open user menu');
        button.textContent = 'EU';
        button.style.width = '36px';
        button.style.height = '36px';
        button.style.borderRadius = '9999px';
        button.style.background = '#e55100';
        button.style.color = 'white';
        node.replaceChildren(button);
      },
      unmountUserButton(node: HTMLElement) {
        node.replaceChildren();
      },
      mountSignIn(node: HTMLElement) {
        const heading = document.createElement('h1');
        heading.textContent = 'Sign in';
        node.replaceChildren(heading);
      },
      unmountSignIn(node: HTMLElement) {
        node.replaceChildren();
      },
      mountSignUp(node: HTMLElement, mountProps?: { forceRedirectUrl?: string }) {
        if (mountProps?.forceRedirectUrl) {
          node.dataset.forceRedirectUrl = mountProps.forceRedirectUrl;
        }
        const wrapper = document.createElement('div');
        const heading = document.createElement('h2');
        heading.textContent = 'Create your account';
        const label = document.createElement('label');
        label.textContent = 'Letterboxd username';
        const input = document.createElement('input');
        input.name = 'username';
        input.required = true;
        input.minLength = 2;
        input.maxLength = 15;
        input.pattern = '[A-Za-z0-9_]{2,15}';
        label.append(input);
        const button = document.createElement('button');
        button.type = 'button';
        button.textContent = 'Continue';
        wrapper.append(heading, label, button);
        node.replaceChildren(wrapper);
      },
      unmountSignUp(node: HTMLElement) {
        node.replaceChildren();
      },
    };
    Object.assign(globalThis, { Clerk: clerk });
  }, { signedIn: authenticated, username: letterboxdUsername ?? 'legacy_user' });

  const state: ApiFixtureState = {
    profiles: profiles.slice(0, options.profileCount ?? profiles.length).map((profile) => ({ ...profile })),
    currentUser: {
      user_id: 'user_e2e',
      is_admin: isAdmin,
      letterboxd_username: letterboxdUsername,
      primary_profile_status: options.primaryProfileStatus ?? (letterboxdUsername ? 'pending' : 'unconfigured'),
    },
    requests: [{
      id: 1,
      requester_user_id: 'user_e2e',
      requested_username: 'queuedprofile',
      status: 'approved',
      note: 'Accepted for the next sync.',
      requested_at: '2026-07-29T10:00:00Z',
      updated_at: '2026-07-29T11:00:00Z',
      resolved_at: '2026-07-29T11:00:00Z',
      resolved_by_user_id: 'admin_e2e',
      profile: null,
    }],
  };
  await page.route('https://clerk.example.test/**', (route) => route.fulfill({ status: 204 }));
  await page.route(/^http:\/\/(?:127\.0\.0\.1|localhost):8000\/.*/, (route) => handleApiRoute(route, state, isAdmin));
  await page.route(MISSING_POSTER_URL, (route) => (
    route.fulfill({ status: 404, contentType: 'image/jpeg', body: '' })
  ));
  await page.route('https://www.themoviedb.org/**', (route) => (
    route.fulfill({
      status: 200,
      contentType: 'image/svg+xml',
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"/>',
    })
  ));
}
