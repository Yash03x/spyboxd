#!/usr/bin/env node

import { constants } from 'node:fs';
import { open } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const MAX_FILE_BYTES = 64 * 1024;
const MAX_RESPONSE_BYTES = 2 * 1024 * 1024;
const USER_ID = /^user_[A-Za-z0-9]+$/;
const SESSION_ID = /^sess_[A-Za-z0-9]+$/;
const PROFILE = /^[A-Za-z0-9_]{2,15}$/;
const TESTING_TOKEN = /^[A-Za-z0-9._~-]{20,2048}$/;
const SIGN_IN_TOKEN = /^[A-Za-z0-9._~-]{20,4096}$/;
const CLERK_CAPABILITY = /^[A-Za-z0-9._~-]{20,8192}$/;
const BROWSER_PLAN_VERSION = 4;
const EXPECTED_SESSION_TOKEN_MAX_LIFETIME_SECONDS = 90;
const TESTING_TOKEN_MIN_REMAINING_SECONDS = 180;
const SIGN_IN_TOKEN_MIN_REMAINING_SECONDS = 120;
const SIGN_IN_TOKEN_CONSUMPTION_MARGIN_SECONDS = 30;
const SIGN_IN_OPERATION_TIMEOUT_MILLISECONDS = 45_000;
const JWT_EXPIRY_GRACE_SECONDS = 5;
const MAX_EXPIRY_OVERHEAD_SECONDS = 30;
const PRIVATE_PROOF_PATH = '/profiles';
const CLOSURES = new Set(['sign_out', 'jwt_expiry']);

class CanaryError extends Error {}

function fail(message) {
  throw new CanaryError(message);
}

function argumentsFromCommandLine() {
  if (process.argv.length !== 4 || process.argv[2] !== '--plan' || !process.argv[3]) {
    fail('Usage: run-production-auth-canary.mjs --plan <file>');
  }
  return { planPath: process.argv[3] };
}

async function readBoundedJson(path, label) {
  let handle;
  try {
    handle = await open(path, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
  } catch {
    fail(`${label} must be a safe regular file`);
  }
  try {
    const metadata = await handle.stat();
    if (
      !metadata.isFile()
      || metadata.size > MAX_FILE_BYTES
      || metadata.uid !== process.geteuid()
      || (metadata.mode & 0o077) !== 0
    ) {
      fail(`${label} must be a private, small regular file`);
    }

    const buffer = Buffer.alloc(MAX_FILE_BYTES + 1);
    let offset = 0;
    while (offset < buffer.length) {
      const { bytesRead } = await handle.read(
        buffer,
        offset,
        buffer.length - offset,
        offset,
      );
      if (bytesRead === 0) break;
      offset += bytesRead;
    }
    if (offset > MAX_FILE_BYTES) {
      fail(`${label} grew beyond its size limit`);
    }
    try {
      return JSON.parse(buffer.subarray(0, offset).toString('utf8'));
    } catch {
      fail(`${label} is not valid JSON`);
    }
  } finally {
    await handle.close();
  }
}

function bareHttpsOrigin(value, label) {
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    fail(`${label} is not a valid URL`);
  }
  if (
    parsed.protocol !== 'https:'
    || parsed.username
    || parsed.password
    || parsed.pathname !== '/'
    || parsed.search
    || parsed.hash
  ) {
    fail(`${label} must be a bare HTTPS origin`);
  }
  return parsed.origin;
}

export function validateTasks(payload, nowSeconds = Math.floor(Date.now() / 1000)) {
  if (
    !payload
    || payload.version !== BROWSER_PLAN_VERSION
    || payload.session_token_max_lifetime_seconds
      !== EXPECTED_SESSION_TOKEN_MAX_LIFETIME_SECONDS
    || !TESTING_TOKEN.test(payload.testing_token ?? '')
    || !Number.isSafeInteger(payload.testing_token_expires_at)
    || payload.testing_token_expires_at - nowSeconds < TESTING_TOKEN_MIN_REMAINING_SECONDS
    || !Array.isArray(payload.tasks)
  ) {
    fail('authenticated canary browser plan is invalid');
  }
  const apiBase = bareHttpsOrigin(payload.api_base, 'API base');
  const appOrigin = bareHttpsOrigin(payload.app_origin, 'application origin');
  const clerkFrontendOrigin = bareHttpsOrigin(
    payload.clerk_frontend_origin,
    'Clerk frontend origin',
  );
  if (apiBase !== 'https://api.spyboxd.com' || appOrigin !== 'https://spyboxd.com') {
    fail('authenticated canary targets an unexpected production origin');
  }
  if (payload.tasks.length !== 2) {
    fail('authenticated canary requires exactly two identities');
  }
  const labels = new Set();
  const userIds = new Set();
  const profiles = new Set();
  const closures = new Set();
  const signInTokens = new Set();
  for (const task of payload.tasks) {
    if (
      !['A', 'B'].includes(task?.label)
      || !CLOSURES.has(task?.closure)
      || !USER_ID.test(task?.user_id ?? '')
      || !PROFILE.test(task?.profile ?? '')
      || !SIGN_IN_TOKEN.test(task?.sign_in_token ?? '')
      || !Number.isSafeInteger(task?.sign_in_token_expires_at)
      || task.sign_in_token_expires_at - nowSeconds
        < SIGN_IN_TOKEN_MIN_REMAINING_SECONDS
    ) {
      fail('authenticated canary identity is invalid');
    }
    labels.add(task.label);
    userIds.add(task.user_id);
    profiles.add(task.profile.toLowerCase());
    closures.add(task.closure);
    signInTokens.add(task.sign_in_token);
  }
  if (
    labels.size !== 2
    || userIds.size !== 2
    || profiles.size !== 2
    || closures.size !== 2
    || signInTokens.size !== 2
  ) {
    fail('authenticated canary identities are not isolated');
  }
  return {
    apiBase,
    appOrigin,
    clerkFrontendOrigin,
    testingToken: payload.testing_token,
    testingTokenExpiresAt: payload.testing_token_expires_at,
    sessionTokenMaxLifetimeSeconds: payload.session_token_max_lifetime_seconds,
    tasks: payload.tasks,
  };
}

export function registerGitHubSecretMask(secret) {
  if (
    process.env.GITHUB_ACTIONS !== 'true'
    || !CLERK_CAPABILITY.test(secret ?? '')
  ) {
    fail('Clerk temporary capability masking is unavailable');
  }
  process.stdout.write(`::add-mask::${secret}\n`);
}

function redactClerkDiagnostic(value, secrets) {
  const redact = (text) => secrets.reduce(
    (result, secret) => result.replaceAll(secret, '[REDACTED_CLERK_CAPABILITY]'),
    text,
  );
  if (typeof value === 'string') {
    return redact(value);
  }
  if (value instanceof Error) {
    const redacted = new Error(redact(value.message));
    redacted.name = value.name;
    return redacted;
  }
  try {
    const serialized = JSON.stringify(value);
    if (secrets.some((secret) => serialized?.includes(secret))) {
      return '[REDACTED_CLERK_DIAGNOSTIC]';
    }
  } catch {
    return '[UNSERIALIZABLE_CLERK_DIAGNOSTIC]';
  }
  return value;
}

export function openClerkCapabilityScope(
  testingToken,
  additionalCapabilities = [],
  maskSecret = registerGitHubSecretMask,
) {
  if (
    typeof maskSecret !== 'function'
    || !TESTING_TOKEN.test(testingToken ?? '')
    || !Array.isArray(additionalCapabilities)
    || additionalCapabilities.some((value) => !SIGN_IN_TOKEN.test(value ?? ''))
    || process.env.CLERK_TESTING_TOKEN !== undefined
    || process.env.CLERK_TESTING_DEBUG !== undefined
  ) {
    fail('Clerk production Testing Token setup is invalid');
  }

  const redactedCapabilities = [];
  const knownCapabilities = new Set();
  const add = (capability) => {
    if (!CLERK_CAPABILITY.test(capability ?? '')) {
      fail('Clerk temporary capability is invalid');
    }
    if (!knownCapabilities.has(capability)) {
      maskSecret(capability);
      knownCapabilities.add(capability);
      redactedCapabilities.push(capability);
    }
  };
  add(testingToken);
  additionalCapabilities.forEach(add);
  const originalWarn = console.warn;
  const originalError = console.error;
  console.warn = (...values) => originalWarn(
    ...values.map((value) => redactClerkDiagnostic(value, redactedCapabilities)),
  );
  console.error = (...values) => originalError(
    ...values.map((value) => redactClerkDiagnostic(value, redactedCapabilities)),
  );
  process.env.CLERK_TESTING_TOKEN = testingToken;

  let closed = false;
  return {
    add,
    close() {
      if (closed) return;
      closed = true;
      delete process.env.CLERK_TESTING_TOKEN;
      console.warn = originalWarn;
      console.error = originalError;
      redactedCapabilities.length = 0;
      knownCapabilities.clear();
    },
  };
}

export async function installClerkTestingToken(
  context,
  clerkFrontendOrigin,
  testingToken,
  setupClerkTestingToken,
) {
  if (
    typeof setupClerkTestingToken !== 'function'
    || !TESTING_TOKEN.test(testingToken ?? '')
    || process.env.CLERK_TESTING_TOKEN !== testingToken
    || process.env.CLERK_TESTING_DEBUG !== undefined
  ) {
    fail('Clerk production Testing Token context setup is invalid');
  }
  const parsedOrigin = new URL(
    bareHttpsOrigin(clerkFrontendOrigin, 'Clerk frontend origin'),
  );
  await setupClerkTestingToken({
    context,
    options: { frontendApiUrl: parsedOrigin.host },
  });
}

export async function consumeSignInTicket(
  page,
  signInToken,
  maskSecret = registerGitHubSecretMask,
) {
  if (
    !SIGN_IN_TOKEN.test(signInToken ?? '')
    || typeof maskSecret !== 'function'
  ) {
    fail('Clerk Sign-in Token setup is invalid');
  }
  maskSecret(signInToken);
  let oneUseTicket = signInToken;
  try {
    await page.waitForFunction(
      () => Boolean(globalThis.Clerk?.loaded),
      undefined,
      { timeout: 30_000 },
    );
    const outcome = await page.evaluate(
      async ({ ticket, timeoutMilliseconds }) => {
        let timeoutId;
        try {
          return await Promise.race([
            (async () => {
              try {
                const clerk = globalThis.Clerk;
                if (!clerk?.loaded || typeof clerk.client?.signIn?.create !== 'function') {
                  return 'sdk_unavailable';
                }
                const signIn = await clerk.client.signIn.create({
                  strategy: 'ticket',
                  ticket,
                });
                if (signIn?.status !== 'complete' || !signIn.createdSessionId) {
                  return 'sign_in_incomplete';
                }
                await clerk.setActive({ session: signIn.createdSessionId });
                return 'complete';
              } catch {
                return 'sign_in_failed';
              }
            })(),
            new Promise((resolveTimeout) => {
              timeoutId = globalThis.setTimeout(
                () => resolveTimeout('sign_in_timeout'),
                timeoutMilliseconds,
              );
            }),
          ]);
        } finally {
          if (timeoutId !== undefined) globalThis.clearTimeout(timeoutId);
        }
      },
      {
        ticket: oneUseTicket,
        timeoutMilliseconds: SIGN_IN_OPERATION_TIMEOUT_MILLISECONDS,
      },
    );
    if (outcome !== 'complete') {
      fail('Clerk did not consume the one-use Sign-in Token');
    }
  } finally {
    oneUseTicket = undefined;
  }
}

export function decodeSession(token, nowSeconds = Math.floor(Date.now() / 1000)) {
  if (typeof token !== 'string' || token.length < 100 || token.split('.').length !== 3) {
    fail('Clerk did not establish a valid session token');
  }
  let payload;
  try {
    payload = JSON.parse(Buffer.from(token.split('.')[1], 'base64url').toString('utf8'));
  } catch {
    fail('Clerk returned an invalid session token');
  }
  if (
    !USER_ID.test(payload?.sub ?? '')
    || !SESSION_ID.test(payload?.sid ?? '')
    || !Number.isSafeInteger(payload?.exp)
    || payload.exp <= nowSeconds
  ) {
    fail('Clerk session token omitted a valid identity or future expiry');
  }
  return {
    userId: payload.sub,
    sessionId: payload.sid,
    expiresAtSeconds: payload.exp,
  };
}

export function expiryProofDeadlineMilliseconds(
  tokenCapturedAtMilliseconds,
  tokenExpiresAtSeconds,
  sessionTokenMaxLifetimeSeconds,
) {
  if (
    !Number.isSafeInteger(tokenCapturedAtMilliseconds)
    || tokenCapturedAtMilliseconds <= 0
    || !Number.isSafeInteger(tokenExpiresAtSeconds)
    || !Number.isSafeInteger(sessionTokenMaxLifetimeSeconds)
    || sessionTokenMaxLifetimeSeconds
      !== EXPECTED_SESSION_TOKEN_MAX_LIFETIME_SECONDS
  ) {
    fail('authenticated canary expiry inputs are invalid');
  }
  const proofDeadline = (tokenExpiresAtSeconds + JWT_EXPIRY_GRACE_SECONDS) * 1000;
  const maximumDeadline = tokenCapturedAtMilliseconds
    + ((sessionTokenMaxLifetimeSeconds + MAX_EXPIRY_OVERHEAD_SECONDS) * 1000);
  if (proofDeadline <= tokenCapturedAtMilliseconds || proofDeadline > maximumDeadline) {
    fail('Clerk JWT expiry exceeds the canary wait bound');
  }
  return proofDeadline;
}

export function isPrivateSignInRedirect(urlValue, appOrigin, privatePath = PRIVATE_PROOF_PATH) {
  let parsed;
  try {
    parsed = new URL(urlValue);
  } catch {
    return false;
  }
  const redirectTargets = parsed.searchParams.getAll('redirect_url');
  return parsed.origin === appOrigin
    && !parsed.username
    && !parsed.password
    && parsed.pathname.replace(/\/+$/, '') === '/sign-in'
    && !parsed.hash
    && parsed.searchParams.size === 1
    && redirectTargets.length === 1
    && redirectTargets[0] === `${appOrigin}${privatePath}`;
}

export async function applicationSessionToken(
  page,
  context,
  appOrigin,
  timeoutMilliseconds = 30_000,
) {
  const hostname = new URL(appOrigin).hostname;
  const deadline = Date.now() + timeoutMilliseconds;
  while (Date.now() < deadline) {
    const sdkToken = await page.evaluate(async () => {
      const clerk = globalThis.Clerk;
      if (!clerk?.loaded || !clerk.session) return null;
      try {
        return await clerk.session.getToken();
      } catch {
        return null;
      }
    }).catch(() => null);
    if (typeof sdkToken === 'string' && sdkToken) {
      return sdkToken;
    }

    // Keep a cookie fallback for Clerk SDK versions that do not expose the
    // global browser object. The returned JWT is still verified by Spyboxd's
    // API before any canary assertion can pass.
    const matching = (await context.cookies(appOrigin)).filter(
      (cookie) => cookie.name === '__session'
        && cookie.secure
        && cookie.domain.replace(/^\./, '') === hostname,
    );
    if (matching.length === 1) {
      return matching[0].value;
    }
    if (matching.length > 1) {
      fail('Clerk established more than one application session');
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  const state = await page.evaluate(() => ({
    clerkPresent: Boolean(globalThis.Clerk),
    clerkLoaded: Boolean(globalThis.Clerk?.loaded),
    sessionPresent: Boolean(globalThis.Clerk?.session),
  })).catch(() => ({ clerkPresent: false, clerkLoaded: false, sessionPresent: false }));
  let pageState = 'unexpected-origin';
  try {
    const current = new URL(page.url());
    if (current.origin === appOrigin) {
      pageState = current.pathname === '/' ? 'public-root' : 'other-app-path';
    }
  } catch {
    pageState = 'invalid-location';
  }
  const clerkState = state.sessionPresent
    ? 'session-present'
    : state.clerkLoaded
      ? 'loaded-without-session'
      : state.clerkPresent
        ? 'present-not-loaded'
        : 'missing';
  fail(`Clerk did not establish an application session in time (${pageState}; ${clerkState})`);
}

async function responseJson(context, apiBase, path, token, expectedStatus, label) {
  const headers = {
    Accept: 'application/json',
    'Cache-Control': 'no-cache',
  };
  if (typeof token === 'string') {
    headers.Authorization = `Bearer ${token}`;
  }
  const response = await context.request.get(`${apiBase}${path}`, {
    failOnStatusCode: false,
    headers,
    timeout: 15_000,
  });
  if (response.status() !== expectedStatus) {
    fail(`${label} returned HTTP ${response.status()}`);
  }
  const body = await response.body();
  if (body.byteLength > MAX_RESPONSE_BYTES) {
    fail(`${label} returned an oversized response`);
  }
  try {
    return JSON.parse(body.toString('utf8'));
  } catch {
    fail(`${label} returned invalid JSON`);
  }
}

async function validateIdentity(context, apiBase, task, other, token) {
  const me = await responseJson(
    context,
    apiBase,
    '/api/me',
    token,
    200,
    `canary ${task.label} identity`,
  );
  if (
    me?.user_id !== task.user_id
    || me?.is_admin !== false
    || typeof me?.letterboxd_username !== 'string'
    || me.letterboxd_username.toLowerCase() !== task.profile.toLowerCase()
  ) {
    fail(`canary ${task.label} did not resolve as its ordinary account`);
  }

  const tracked = await responseJson(
    context,
    apiBase,
    '/profiles/tracked',
    token,
    200,
    `canary ${task.label} tracked profiles`,
  );
  if (!Array.isArray(tracked?.profiles)) {
    fail(`canary ${task.label} tracked profiles returned an invalid contract`);
  }
  if (tracked.profiles.some((item) => typeof item?.username !== 'string')) {
    fail(`canary ${task.label} tracked profiles returned an invalid identity`);
  }
  const usernames = new Set(
    tracked.profiles.map((item) => item.username.toLowerCase()),
  );
  if (usernames.size !== 1 || !usernames.has(task.profile.toLowerCase())) {
    fail(`canary ${task.label} monitoring data is not isolated`);
  }

  const ownAnalysis = await responseJson(
    context,
    apiBase,
    `/profiles/${encodeURIComponent(task.profile)}/analysis`,
    token,
    200,
    `canary ${task.label} own profile`,
  );
  if (
    typeof ownAnalysis?.username !== 'string'
    || ownAnalysis.username.toLowerCase() !== task.profile.toLowerCase()
  ) {
    fail(`canary ${task.label} own profile returned the wrong identity`);
  }
  await responseJson(
    context,
    apiBase,
    `/profiles/${encodeURIComponent(other.profile)}/analysis`,
    token,
    403,
    `canary ${task.label} cross-profile denial`,
  );
  const pairQuery = new URLSearchParams([
    ['profiles', task.profile],
    ['profiles', other.profile],
  ]).toString();
  await responseJson(
    context,
    apiBase,
    `/api/pair-dossier?${pairQuery}`,
    token,
    403,
    `canary ${task.label} cross-profile insight denial`,
  );
  const activityQuery = new URLSearchParams([
    ['profiles', other.profile],
  ]).toString();
  await responseJson(
    context,
    apiBase,
    `/api/recent-changes?${activityQuery}`,
    token,
    403,
    `canary ${task.label} cross-profile activity denial`,
  );
  await responseJson(
    context,
    apiBase,
    '/api/dashboard/analytics?scope=global',
    token,
    403,
    `canary ${task.label} global-scope denial`,
  );
  await responseJson(
    context,
    apiBase,
    '/admin/profile-requests',
    token,
    403,
    `canary ${task.label} admin denial`,
  );
}

function requireDetail(payload, expected, label) {
  if (!payload || payload.detail !== expected) {
    fail(`${label} returned an unexpected authentication error`);
  }
}

async function proveAnonymousPrivateBoundary(page, context, apiBase, appOrigin, label) {
  const anonymousMe = await responseJson(
    context,
    apiBase,
    '/api/me',
    undefined,
    401,
    `${label} anonymous API boundary`,
  );
  requireDetail(anonymousMe, 'Missing authorization token', `${label} anonymous API boundary`);

  await page.goto(`${appOrigin}${PRIVATE_PROOF_PATH}`, {
    waitUntil: 'domcontentloaded',
    timeout: 45_000,
  });
  await page.waitForURL(
    (url) => isPrivateSignInRedirect(url.href, appOrigin),
    { timeout: 45_000 },
  );
}

export async function proveSignOutClosure(page, context, apiBase, appOrigin, label) {
  const signOut = page.getByRole('button', { name: 'Sign out', exact: true });
  await signOut.waitFor({ state: 'visible', timeout: 30_000 });
  await signOut.click({ timeout: 30_000 });
  await page.waitForURL(
    (url) => url.origin === appOrigin && url.pathname === '/' && !url.search && !url.hash,
    { timeout: 45_000 },
  );
  await page.getByRole('link', { name: 'Sign in to monitor profiles', exact: true }).waitFor({
    state: 'visible',
    timeout: 30_000,
  });
  await proveAnonymousPrivateBoundary(page, context, apiBase, appOrigin, label);
}

export async function proveJwtExpiryClosure(
  page,
  context,
  apiBase,
  label,
  token,
  tokenCapturedAtMilliseconds,
  tokenExpiresAtSeconds,
  sessionTokenMaxLifetimeSeconds,
) {
  // This proves the API rejects the exact captured bearer after its exp. It does
  // not claim the ordinary browser session expired: the VPS guardian separately
  // revokes that session and requires two empty server-side samples.
  const proofDeadline = expiryProofDeadlineMilliseconds(
    tokenCapturedAtMilliseconds,
    tokenExpiresAtSeconds,
    sessionTokenMaxLifetimeSeconds,
  );
  const remainingMilliseconds = proofDeadline - Date.now();
  const maximumWaitMilliseconds = (
    sessionTokenMaxLifetimeSeconds + MAX_EXPIRY_OVERHEAD_SECONDS
  ) * 1000;
  if (remainingMilliseconds > maximumWaitMilliseconds) {
    fail(`${label} expiry proof exceeded its bounded wait`);
  }
  if (remainingMilliseconds > 0) {
    await page.waitForTimeout(remainingMilliseconds);
  }

  const expiredMe = await responseJson(
    context,
    apiBase,
    '/api/me',
    token,
    401,
    `${label} expired JWT boundary`,
  );
  requireDetail(expiredMe, 'Token has expired', `${label} expired JWT boundary`);
}

async function main() {
  const { planPath } = argumentsFromCommandLine();
  const taskContract = validateTasks(await readBoundedJson(planPath, 'browser plan'));

  const [{ chromium }, { setupClerkTestingToken }] = await Promise.all([
    import('playwright'),
    import('@clerk/testing/playwright'),
  ]);
  let browser;
  let capabilityScope;
  let testingToken = taskContract.testingToken;
  const runtimes = [];
  try {
    browser = await chromium.launch({ headless: true });
    const signInTokens = taskContract.tasks.map((task) => task.sign_in_token);
    capabilityScope = openClerkCapabilityScope(testingToken, signInTokens);
    signInTokens.length = 0;
    taskContract.testingToken = undefined;

    // Consume both jointly-created tickets before any slower profile/API/UI
    // assertions. This removes the possibility that identity B's one-use
    // capability expires while identity A is being validated.
    for (let index = 0; index < taskContract.tasks.length; index += 1) {
      const task = taskContract.tasks[index];
      const other = taskContract.tasks[1 - index];
      const context = await browser.newContext({
        acceptDownloads: false,
        serviceWorkers: 'block',
      });
      const runtime = {
        task,
        other,
        context,
        page: undefined,
        token: undefined,
        tokenCapturedAtMilliseconds: undefined,
        session: undefined,
      };
      runtimes.push(runtime);
      await installClerkTestingToken(
        context,
        taskContract.clerkFrontendOrigin,
        testingToken,
        setupClerkTestingToken,
      );
      const page = await context.newPage();
      runtime.page = page;
      await page.goto(taskContract.appOrigin, {
        waitUntil: 'domcontentloaded',
        timeout: 45_000,
      });
      if (
        task.sign_in_token_expires_at - Math.floor(Date.now() / 1000)
        < SIGN_IN_TOKEN_CONSUMPTION_MARGIN_SECONDS
      ) {
        fail(`canary ${task.label} Sign-in Token is too close to expiry`);
      }
      const signInToken = task.sign_in_token;
      try {
        await consumeSignInTicket(page, signInToken, capabilityScope.add);
      } finally {
        task.sign_in_token = undefined;
      }
      const token = await applicationSessionToken(
        page,
        context,
        taskContract.appOrigin,
      );
      capabilityScope.add(token);
      runtime.token = token;
      runtime.tokenCapturedAtMilliseconds = Date.now();
      runtime.session = decodeSession(token);
      if (runtime.session.userId !== task.user_id) {
        fail(`Clerk resolved the wrong canary ${task.label} identity`);
      }
    }

    await Promise.all(runtimes.map(async (runtime) => {
      const {
        task,
        other,
        context,
        page,
        token,
        tokenCapturedAtMilliseconds,
        session,
      } = runtime;
      if (!page || !token || !session || !tokenCapturedAtMilliseconds) {
        fail(`canary ${task.label} browser session was not established`);
      }
      await page.goto(`${taskContract.appOrigin}/profiles`, {
        waitUntil: 'domcontentloaded',
        timeout: 45_000,
      });
      await page.waitForURL(
        (url) => url.origin === taskContract.appOrigin
          && url.pathname === '/profiles'
          && !url.search
          && !url.hash,
        { timeout: 45_000 },
      );
      await validateIdentity(context, taskContract.apiBase, task, other, token);
      if (task.closure === 'sign_out') {
        await proveSignOutClosure(
          page,
          context,
          taskContract.apiBase,
          taskContract.appOrigin,
          `canary ${task.label}`,
        );
      } else if (task.closure === 'jwt_expiry') {
        await proveJwtExpiryClosure(
          page,
          context,
          taskContract.apiBase,
          `canary ${task.label}`,
          token,
          tokenCapturedAtMilliseconds,
          session.expiresAtSeconds,
          taskContract.sessionTokenMaxLifetimeSeconds,
        );
      } else {
        fail(`canary ${task.label} has an unsupported closure proof`);
      }
    }));
  } finally {
    testingToken = undefined;
    for (const task of taskContract.tasks) {
      task.sign_in_token = undefined;
    }
    let cleanupFailed = false;
    for (const runtime of runtimes.reverse()) {
      runtime.token = undefined;
      if (runtime.context) {
        try {
          await runtime.context.clearCookies();
          await runtime.context.close();
        } catch {
          cleanupFailed = true;
        }
      }
    }
    capabilityScope?.close();
    if (browser) {
      try {
        await browser.close();
      } catch {
        cleanupFailed = true;
      }
    }
    if (cleanupFailed) {
      fail('browser canary context cleanup failed');
    }
  }
  process.stdout.write(
    'authenticated browser canary passed: two-user isolation, sign-out, and captured JWT expiry proven\n',
  );
}

const invokedPath = process.argv[1] ? pathToFileURL(resolve(process.argv[1])).href : '';
if (import.meta.url === invokedPath) {
  main().catch((error) => {
    const detail = error instanceof CanaryError
      ? error.message
      : 'browser-backed isolation check failed';
    process.stderr.write(`authenticated production canary failed: ${detail}\n`);
    process.exitCode = 1;
  });
}
