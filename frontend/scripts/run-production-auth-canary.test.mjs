import assert from 'node:assert/strict';
import test from 'node:test';
import { setupClerkTestingToken as realSetupClerkTestingToken } from '@clerk/testing/playwright';

import {
  applicationSessionToken,
  consumeSignInTicket,
  decodeSession,
  expiryProofDeadlineMilliseconds,
  installClerkTestingToken,
  isPrivateSignInRedirect,
  openClerkCapabilityScope,
  proveJwtExpiryClosure,
  proveSignOutClosure,
  validateTasks,
} from './run-production-auth-canary.mjs';

const APP_ORIGIN = 'https://spyboxd.com';
const CLERK_FRONTEND_ORIGIN = 'https://clerk.spyboxd.com';

function task(label, closure, userId, profile) {
  return {
    label,
    closure,
    user_id: userId,
    profile,
    sign_in_token: `ticket-${label.toLowerCase()}-${label.toLowerCase().repeat(48)}`,
    sign_in_token_expires_at: Math.floor(Date.now() / 1000) + 300,
  };
}

function plan() {
  return {
    version: 4,
    api_base: 'https://api.spyboxd.com',
    app_origin: APP_ORIGIN,
    clerk_frontend_origin: CLERK_FRONTEND_ORIGIN,
    testing_token: `testing-${'a'.repeat(48)}`,
    testing_token_expires_at: Math.floor(Date.now() / 1000) + 600,
    session_token_max_lifetime_seconds: 90,
    tasks: [
      task('A', 'sign_out', 'user_A123', 'alpha'),
      task('B', 'jwt_expiry', 'user_B123', 'beta'),
    ],
  };
}

function token(payload) {
  const encodedHeader = Buffer.from(JSON.stringify({ alg: 'RS256', typ: 'JWT' }))
    .toString('base64url');
  const encodedPayload = Buffer.from(JSON.stringify(payload)).toString('base64url');
  return `${encodedHeader}.${encodedPayload}.${'s'.repeat(96)}`;
}

test('browser plan requires distinct sign-out and captured-JWT-expiry closures', () => {
  const contract = validateTasks(plan());
  assert.equal(contract.sessionTokenMaxLifetimeSeconds, 90);
  assert.deepEqual(contract.tasks.map((item) => item.closure), ['sign_out', 'jwt_expiry']);

  const duplicated = plan();
  duplicated.tasks[1].closure = 'sign_out';
  assert.throws(() => validateTasks(duplicated), /not isolated/);

  const wrongDuration = plan();
  wrongDuration.session_token_max_lifetime_seconds = 1800;
  assert.throws(() => validateTasks(wrongDuration), /browser plan is invalid/);

  const expiredTestingToken = plan();
  expiredTestingToken.testing_token_expires_at = Math.floor(Date.now() / 1000) + 30;
  assert.throws(() => validateTasks(expiredTestingToken), /browser plan is invalid/);

  const expiringTicket = plan();
  expiringTicket.tasks[1].sign_in_token_expires_at = Math.floor(Date.now() / 1000) + 30;
  assert.throws(() => validateTasks(expiringTicket), /identity is invalid/);

  const duplicateTicket = plan();
  duplicateTicket.tasks[1].sign_in_token = duplicateTicket.tasks[0].sign_in_token;
  assert.throws(() => validateTasks(duplicateTicket), /not isolated/);

  const undocumentedTestingTokenLifetime = plan();
  undocumentedTestingTokenLifetime.testing_token_expires_at += 86_400;
  assert.doesNotThrow(() => validateTasks(undocumentedTestingTokenLifetime));
});

test('Clerk Testing Token and one-use ticket are masked before helper setup', async () => {
  const events = [];
  const diagnostics = [];
  const context = {};
  const testingToken = `testing-${'b'.repeat(48)}`;
  const signInToken = `ticket-${'d'.repeat(48)}`;
  const originalWarn = console.warn;
  const originalError = console.error;
  console.warn = (...values) => diagnostics.push(values.map(String).join(' '));
  console.error = (...values) => diagnostics.push(values.map(String).join(' '));
  let capabilityScope;
  try {
    capabilityScope = openClerkCapabilityScope(
      testingToken,
      [signInToken],
      (secret) => events.push(['mask', secret]),
    );
    await installClerkTestingToken(
      context,
      CLERK_FRONTEND_ORIGIN,
      testingToken,
      async (options) => {
        assert.equal(options.context, context);
        assert.deepEqual(options.options, { frontendApiUrl: 'clerk.spyboxd.com' });
        assert.equal(process.env.CLERK_TESTING_TOKEN, testingToken);
        console.warn(`Clerk retry URL contained ${testingToken}`);
        console.error(new Error(`Clerk route failed with ${signInToken}`));
        events.push(['setup']);
      },
    );
    assert.deepEqual(events, [
      ['mask', testingToken],
      ['mask', signInToken],
      ['setup'],
    ]);
  } finally {
    capabilityScope?.close();
    console.warn = originalWarn;
    console.error = originalError;
  }
  assert.equal(process.env.CLERK_TESTING_TOKEN, undefined);
  assert.equal(diagnostics.some((line) => line.includes(testingToken)), false);
  assert.equal(diagnostics.some((line) => line.includes(signInToken)), false);
  assert.equal(
    diagnostics.filter((line) => line.includes('[REDACTED_CLERK_CAPABILITY]')).length,
    2,
  );
});

test('real Clerk helper failure diagnostics cannot expose the production Testing Token', async () => {
  const testingToken = `testing-${'c'.repeat(48)}`;
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
  let capabilityScope;
  try {
    capabilityScope = openClerkCapabilityScope(
      testingToken,
      [],
      () => {},
    );
    await installClerkTestingToken(
      context,
      CLERK_FRONTEND_ORIGIN,
      testingToken,
      realSetupClerkTestingToken,
    );
    assert.equal(handlers.length, 1);
    const fapiHandler = handlers[0].handler;
    let fetches = 0;
    await fapiHandler({
      request: () => ({ url: () => `${CLERK_FRONTEND_ORIGIN}/v1/client` }),
      fetch: async ({ url }) => {
        fetches += 1;
        throw new Error(`simulated FAPI failure for ${url}`);
      },
      continue: async () => {},
    });
    assert.equal(fetches, 4);
  } finally {
    capabilityScope?.close();
    console.warn = originalWarn;
    globalThis.setTimeout = originalSetTimeout;
  }
  assert.equal(process.env.CLERK_TESTING_TOKEN, undefined);
  assert.equal(diagnostics.length, 1);
  assert.equal(diagnostics[0].includes(testingToken), false);
  assert.match(diagnostics[0], /REDACTED_CLERK_CAPABILITY/);
});

test('Sign-in ticket uses ClerkJS ticket strategy and activates the session', async () => {
  const events = [];
  const signInToken = `ticket-${'e'.repeat(48)}`;
  const originalClerk = globalThis.Clerk;
  const page = {
    async waitForFunction() { events.push('clerk-loaded'); },
    async evaluate(callback, ticketValue) {
      assert.deepEqual(ticketValue, {
        ticket: signInToken,
        timeoutMilliseconds: 45_000,
      });
      globalThis.Clerk = {
        loaded: true,
        client: {
          signIn: {
            async create(input) {
              assert.deepEqual(input, { strategy: 'ticket', ticket: signInToken });
              events.push('ticket-consumed');
              return { status: 'complete', createdSessionId: 'sess_A123' };
            },
          },
        },
        async setActive(input) {
          assert.deepEqual(input, { session: 'sess_A123' });
          events.push('session-activated');
        },
      };
      try {
        return await callback(ticketValue);
      } finally {
        if (originalClerk === undefined) delete globalThis.Clerk;
        else globalThis.Clerk = originalClerk;
      }
    },
  };
  await consumeSignInTicket(
    page,
    signInToken,
    (secret) => events.push(`masked:${secret === signInToken}`),
  );
  assert.deepEqual(events, [
    'masked:true',
    'clerk-loaded',
    'ticket-consumed',
    'session-activated',
  ]);
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

test('expiry proof deadline covers only the captured JWT within a strict bound', () => {
  const tokenCapturedAt = 1_000_000;
  assert.equal(
    expiryProofDeadlineMilliseconds(tokenCapturedAt, 1_060, 90),
    1_065_000,
  );
  assert.throws(
    () => expiryProofDeadlineMilliseconds(tokenCapturedAt, 1_200, 90),
    /JWT expiry exceeds the canary wait bound/,
  );
});

test('JWT closure proves the fixed bearer expired without claiming browser sign-out', async () => {
  const now = Date.now();
  const expiry = Math.floor(now / 1000) + 60;
  const events = [];
  const page = {
    async waitForTimeout(milliseconds) {
      assert.ok(milliseconds > 0 && milliseconds <= 120_000);
      events.push('waited-for-jwt-expiry');
    },
  };
  const context = {
    request: {
      async get(url, options) {
        assert.equal(url, 'https://api.spyboxd.com/api/me');
        assert.equal(options.headers.Authorization, 'Bearer captured-jwt');
        events.push('expired-bearer-rejected');
        return {
          status: () => 401,
          body: async () => Buffer.from(JSON.stringify({
            detail: 'Token has expired',
          })),
        };
      },
    },
  };

  await proveJwtExpiryClosure(
    page,
    context,
    'https://api.spyboxd.com',
    'canary B',
    'captured-jwt',
    now,
    expiry,
    90,
  );
  assert.deepEqual(events, [
    'waited-for-jwt-expiry',
    'expired-bearer-rejected',
  ]);
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
