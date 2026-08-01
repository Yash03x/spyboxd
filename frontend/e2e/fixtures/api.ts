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
  join_date: '2020-01-01',
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

const groupSignals = {
  summary: {
    profiles_analyzed: profiles.length,
    profiles_with_diary_dates: profiles.length,
    shared_titles: 42,
    same_day_events: 1,
    one_day_gap_events: 0,
    same_day_pair_hits: 1,
    one_day_gap_pair_hits: 0,
    gap_days: 1,
    gap_events: 1,
    gap_pair_hits: 1,
    most_shared_title: sharedMovie,
    strongest_alignment_pair: pair,
    most_divisive_title: sharedMovie,
  },
  same_day_events: [signalEvent],
  one_day_gap_events: [],
  gap_events: [signalEvent],
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
      },
      {
        position: 2,
        title: 'Favourite Two',
        year: 2004,
        poster_url: null,
        letterboxd_url: 'https://letterboxd.com/film/favourite-two/',
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
    return json(route, { generated_at: '2026-07-29T12:00:00Z', scope: 'latest_sync', changes: [] });
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
        echoes: 0,
        movies: 0,
        same_day: 0,
        within_gap: 0,
        first_known_plus_rewatch: 0,
        rewatch_plus_rewatch: 0,
        date_coverage_ratio: 1,
      },
      echoes: [],
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

  // Social graph (contract-shaped empty states until fixtures grow edges).
  if (path === '/api/follow-graph/suggestions') return json(route, { suggestions: [] });
  if (path === '/api/follow-graph/mutuals') {
    return json(route, { profiles: [], pairs: [], rollups: {} });
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
