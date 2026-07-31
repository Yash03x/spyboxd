import assert from 'node:assert/strict';
import test from 'node:test';
import { setupClerkTestingToken as realSetupClerkTestingToken } from '@clerk/testing/playwright';

import {
  applicationSessionToken,
  decodeSession,
  expiryProofDeadlineMilliseconds,
  installClerkTestingToken,
  isPrivateSignInRedirect,
  proveSignOutClosure,
  validateTasks,
} from './run-production-auth-canary.mjs';

const APP_ORIGIN = 'https://spyboxd.com';
const TASK_ORIGIN = 'https://clerk.spyboxd.com';

function task(label, closure, userId, profile) {
  return {
    label,
    closure,
    user_id: userId,
    profile,
    task_url: `${TASK_ORIGIN}/v1/agent-tasks/${label.toLowerCase()}-ticket`,
  };
}

function plan() {
  return {
    version: 3,
    api_base: 'https://api.spyboxd.com',
    app_origin: APP_ORIGIN,
    task_origin: TASK_ORIGIN,
    testing_token: `testing-${'a'.repeat(48)}`,
    testing_token_expires_at: Math.floor(Date.now() / 1000) + 600,
    session_max_duration_seconds: 120,
    tasks: [
      task('A', 'sign_out', 'user_A123', 'alpha'),
      task('B', 'session_expiry', 'user_B123', 'beta'),
    ],
  };
}

function token(payload) {
  const encodedHeader = Buffer.from(JSON.stringify({ alg: 'RS256', typ: 'JWT' }))
    .toString('base64url');
  const encodedPayload = Buffer.from(JSON.stringify(payload)).toString('base64url');
  return `${encodedHeader}.${encodedPayload}.${'s'.repeat(96)}`;
}

test('browser plan requires distinct sign-out and natural-expiry closures', () => {
  const contract = validateTasks(plan());
  assert.equal(contract.sessionMaxDurationSeconds, 120);
  assert.deepEqual(contract.tasks.map((item) => item.closure), ['sign_out', 'session_expiry']);

  const duplicated = plan();
  duplicated.tasks[1].closure = 'sign_out';
  assert.throws(() => validateTasks(duplicated), /not isolated identities/);

  const wrongDuration = plan();
  wrongDuration.session_max_duration_seconds = 1800;
  assert.throws(() => validateTasks(wrongDuration), /task contract is invalid/);

  const expiredTestingToken = plan();
  expiredTestingToken.testing_token_expires_at = Math.floor(Date.now() / 1000) + 30;
  assert.throws(() => validateTasks(expiredTestingToken), /task contract is invalid/);
});

test('Clerk Testing Token is installed before one-use task navigation and cleared', async () => {
  const events = [];
  const diagnostics = [];
  let taskHandler;
  const context = {
    async route(url, handler, options) {
      events.push(['route', url, options]);
      taskHandler = handler;
    },
  };
  const testingToken = `testing-${'b'.repeat(48)}`;
  const taskUrl = `${TASK_ORIGIN}/v1/agent-tasks/a-ticket`;
  const originalWarn = console.warn;
  const originalError = console.error;
  console.warn = (...values) => diagnostics.push(values.map(String).join(' '));
  console.error = (...values) => diagnostics.push(values.map(String).join(' '));
  let clear;
  try {
    clear = await installClerkTestingToken(
      context,
      taskUrl,
      TASK_ORIGIN,
      testingToken,
      async (options) => {
        assert.equal(options.context, context);
        assert.deepEqual(options.options, { frontendApiUrl: 'clerk.spyboxd.com' });
        assert.equal(process.env.CLERK_TESTING_TOKEN, testingToken);
        console.warn(`Clerk retry URL contained ${testingToken}`);
        console.error(new Error(`Clerk route failed with ${testingToken}`));
        events.push(['setup']);
      },
      (secret) => events.push(['mask', secret]),
    );
    assert.deepEqual(events, [
      ['mask', testingToken],
      ['setup'],
      ['route', taskUrl, { times: 1 }],
    ]);

    let continuedUrl;
    await taskHandler({
      request: () => ({ url: () => taskUrl }),
      continue: async ({ url }) => { continuedUrl = new URL(url); },
    });
    assert.equal(continuedUrl.origin, TASK_ORIGIN);
    assert.equal(continuedUrl.pathname, '/v1/agent-tasks/a-ticket');
    assert.equal(continuedUrl.searchParams.get('__clerk_testing_token'), testingToken);
  } finally {
    clear?.();
    console.warn = originalWarn;
    console.error = originalError;
  }
  assert.equal(process.env.CLERK_TESTING_TOKEN, undefined);
  assert.equal(diagnostics.some((line) => line.includes(testingToken)), false);
  assert.equal(
    diagnostics.filter((line) => line.includes('[REDACTED_TESTING_TOKEN]')).length,
    2,
  );
});

test('real Clerk helper failure diagnostics cannot expose the production Testing Token', async () => {
  const testingToken = `testing-${'c'.repeat(48)}`;
  const taskUrl = `${TASK_ORIGIN}/v1/agent-tasks/a-ticket`;
  const handlers = [];
  const context = {
    async route(matcher, handler) {
      handlers.push({ matcher, handler });
    },
  };
  const diagnostics = [];
  const originalWarn = console.warn;
  const originalSetTimeout = globalThis.setTimeout;
  console.warn = (...values) => diagnostics.push(values.map(String).join(' '));
  globalThis.setTimeout = (callback) => {
    callback();
    return 0;
  };
  let clear;
  try {
    clear = await installClerkTestingToken(
      context,
      taskUrl,
      TASK_ORIGIN,
      testingToken,
      realSetupClerkTestingToken,
      () => {},
    );
    assert.equal(handlers.length, 2);
    const fapiHandler = handlers[0].handler;
    let fetches = 0;
    await fapiHandler({
      request: () => ({ url: () => `${TASK_ORIGIN}/v1/client` }),
      fetch: async ({ url }) => {
        fetches += 1;
        throw new Error(`simulated FAPI failure for ${url}`);
      },
      continue: async () => {},
    });
    assert.equal(fetches, 4);
  } finally {
    clear?.();
    console.warn = originalWarn;
    globalThis.setTimeout = originalSetTimeout;
  }
  assert.equal(process.env.CLERK_TESTING_TOKEN, undefined);
  assert.equal(diagnostics.length, 1);
  assert.equal(diagnostics[0].includes(testingToken), false);
  assert.match(diagnostics[0], /REDACTED_TESTING_TOKEN/);
});

test('session token contract requires a future expiry and session identity', () => {
  const decoded = decodeSession(token({
    sub: 'user_A123',
    sid: 'sess_A123',
    exp: 1_060,
  }), 1_000);
  assert.deepEqual(decoded, {
    userId: 'user_A123',
    sessionId: 'sess_A123',
    expiresAtSeconds: 1_060,
  });

  assert.throws(
    () => decodeSession(token({ sub: 'user_A123', sid: 'sess_A123', exp: 999 }), 1_000),
    /future expiry/,
  );
  assert.throws(
    () => decodeSession(token({ sub: 'user_A123', exp: 1_060 }), 1_000),
    /valid identity/,
  );
});

test('application session handoff prefers Clerk SDK token with a cookie fallback', async () => {
  const sdkToken = token({ sub: 'user_A123', sid: 'sess_A123', exp: 1_060 });
  assert.equal(await applicationSessionToken(
    {
      async evaluate(callback) {
        const originalClerk = globalThis.Clerk;
        globalThis.Clerk = {
          loaded: true,
          session: { getToken: async () => sdkToken },
        };
        try {
          return await callback();
        } finally {
          if (originalClerk === undefined) {
            delete globalThis.Clerk;
          } else {
            globalThis.Clerk = originalClerk;
          }
        }
      },
    },
    { cookies: async () => [] },
    APP_ORIGIN,
    1_000,
  ), sdkToken);

  const cookieToken = token({ sub: 'user_B123', sid: 'sess_B123', exp: 1_060 });
  assert.equal(await applicationSessionToken(
    { evaluate: async () => null },
    {
      cookies: async () => [{
        name: '__session',
        value: cookieToken,
        secure: true,
        domain: '.spyboxd.com',
      }],
    },
    APP_ORIGIN,
    1_000,
  ), cookieToken);
});

test('expiry proof deadline covers both JWT and Agent Task session expiry', () => {
  const sessionStartedAt = 1_000_000;
  assert.equal(
    expiryProofDeadlineMilliseconds(sessionStartedAt, 1_060, 120),
    1_135_000,
  );
  assert.throws(
    () => expiryProofDeadlineMilliseconds(sessionStartedAt, 1_200, 120),
    /JWT expiry exceeds the bounded Agent Task session/,
  );
});

test('private redirect proof remains exact and same-origin', () => {
  assert.equal(isPrivateSignInRedirect(
    'https://spyboxd.com/sign-in?redirect_url=https%3A%2F%2Fspyboxd.com%2Fprofiles',
    APP_ORIGIN,
  ), true);
  assert.equal(isPrivateSignInRedirect(
    'https://evil.example/sign-in?redirect_url=https%3A%2F%2Fspyboxd.com%2Fprofiles',
    APP_ORIGIN,
  ), false);
  assert.equal(isPrivateSignInRedirect(
    'https://spyboxd.com/sign-in?redirect_url=https%3A%2F%2Fevil.example%2Fprofiles',
    APP_ORIGIN,
  ), false);
  assert.equal(isPrivateSignInRedirect(
    'https://spyboxd.com/sign-in?redirect_url=https%3A%2F%2Fspyboxd.com%2Fprofiles&extra=1',
    APP_ORIGIN,
  ), false);
});

test('sign-out closure clicks the real control then proves UI and API denial', async () => {
  const events = [];
  const redirect = new URL(
    'https://spyboxd.com/sign-in?redirect_url=https%3A%2F%2Fspyboxd.com%2Fprofiles',
  );
  const urls = [new URL(APP_ORIGIN), redirect];
  const page = {
    getByRole(role, options) {
      if (role === 'button' && options.name === 'Sign out') {
        return {
          async waitFor() { events.push('sign-out-visible'); },
          async click() { events.push('sign-out-clicked'); },
        };
      }
      if (role === 'link' && options.name === 'Sign in to monitor profiles') {
        return {
          async waitFor() { events.push('sign-in-visible'); },
        };
      }
      throw new Error('unexpected role lookup');
    },
    async waitForURL(predicate) {
      assert.equal(predicate(urls.shift()), true);
    },
    async goto(url) {
      assert.equal(url, `${APP_ORIGIN}/profiles`);
      events.push('private-route-requested');
    },
  };
  const context = {
    request: {
      async get(url, options) {
        assert.equal(url, 'https://api.spyboxd.com/api/me');
        assert.equal(options.headers.Authorization, undefined);
        events.push('anonymous-api-denied');
        return {
          status: () => 401,
          body: async () => Buffer.from(JSON.stringify({
            detail: 'Missing authorization token',
          })),
        };
      },
    },
  };

  await proveSignOutClosure(
    page,
    context,
    'https://api.spyboxd.com',
    APP_ORIGIN,
    'canary A',
  );
  assert.deepEqual(events, [
    'sign-out-visible',
    'sign-out-clicked',
    'sign-in-visible',
    'anonymous-api-denied',
    'private-route-requested',
  ]);
  assert.equal(urls.length, 0);
});
