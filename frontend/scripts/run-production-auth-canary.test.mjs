import assert from 'node:assert/strict';
import test from 'node:test';

import {
  applicationSessionToken,
  decodeSession,
  expiryProofDeadlineMilliseconds,
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
    version: 2,
    api_base: 'https://api.spyboxd.com',
    app_origin: APP_ORIGIN,
    task_origin: TASK_ORIGIN,
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
