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
  agreements: [],
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

  if (route.request().headers().authorization !== 'Bearer e2e-token') {
    return route.fulfill({
      status: 401,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Missing fixture bearer token' }),
    });
  }

  if (path === '/api/me') return json(route, { user_id: 'user_e2e', is_admin: isAdmin });
  if (path === '/profiles' && method === 'GET') return json(route, { profiles: state.profiles });
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
        { month: '2026-06', movies_watched: 20, average_rating: 3.8 },
        { month: '2026-07', movies_watched: 24, average_rating: 3.9 },
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

  return route.fulfill({
    status: 404,
    contentType: 'application/json',
    body: JSON.stringify({ detail: `No e2e fixture for ${path}` }),
  });
}

export async function installApiMocks(
  page: Page,
  options: { authenticated?: boolean; isAdmin?: boolean; profileCount?: number } = {},
) {
  const authenticated = options.authenticated ?? true;
  const isAdmin = options.isAdmin ?? false;

  if (authenticated) {
    await page.context().addCookies([{
      name: 'spyboxd-e2e-auth',
      value: '1',
      domain: 'localhost',
      path: '/',
    }]);
  }

  await page.addInitScript(({ signedIn }) => {
    const user = signedIn ? {
      id: 'user_e2e',
      firstName: 'E2E',
      lastName: 'User',
      fullName: 'E2E User',
      username: 'e2e-user',
      imageUrl: '',
      hasImage: false,
      organizationMemberships: [],
    } : null;
    const session = signedIn ? {
      id: 'sess_e2e',
      status: 'active',
      user,
      factorVerificationAge: null,
      actor: null,
      lastActiveToken: { jwt: { claims: { sub: 'user_e2e', sid: 'sess_e2e' } } },
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
      isSignedIn: false,
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
      signOut: async () => undefined,
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
    };
    Object.assign(globalThis, { Clerk: clerk });
  }, { signedIn: authenticated });

  const state: ApiFixtureState = {
    profiles: profiles.slice(0, options.profileCount ?? profiles.length).map((profile) => ({ ...profile })),
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
