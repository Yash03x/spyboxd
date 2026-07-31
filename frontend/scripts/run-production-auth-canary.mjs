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
const BROWSER_PLAN_VERSION = 2;
const EXPECTED_SESSION_MAX_DURATION_SECONDS = 120;
const JWT_EXPIRY_GRACE_SECONDS = 5;
const SESSION_EXPIRY_GRACE_SECONDS = 15;
const MAX_EXPIRY_OVERHEAD_SECONDS = 30;
const PRIVATE_PROOF_PATH = '/profiles';
const CLOSURES = new Set(['sign_out', 'session_expiry']);

class CanaryError extends Error {}

function fail(message) {
  throw new CanaryError(message);
}

function argumentsFromCommandLine() {
  if (process.argv.length !== 4 || process.argv[2] !== '--tasks' || !process.argv[3]) {
    fail('Usage: run-production-auth-canary.mjs --tasks <file>');
  }
  return { tasksPath: process.argv[3] };
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

export function validateTasks(payload) {
  if (
    !payload
    || payload.version !== BROWSER_PLAN_VERSION
    || payload.session_max_duration_seconds !== EXPECTED_SESSION_MAX_DURATION_SECONDS
    || !Array.isArray(payload.tasks)
  ) {
    fail('authenticated canary task contract is invalid');
  }
  const apiBase = bareHttpsOrigin(payload.api_base, 'API base');
  const appOrigin = bareHttpsOrigin(payload.app_origin, 'application origin');
  const taskOrigin = bareHttpsOrigin(payload.task_origin, 'Clerk task origin');
  if (apiBase !== 'https://api.spyboxd.com' || appOrigin !== 'https://spyboxd.com') {
    fail('authenticated canary targets an unexpected production origin');
  }
  if (payload.tasks.length !== 2) {
    fail('authenticated canary requires exactly two tasks');
  }
  const labels = new Set();
  const userIds = new Set();
  const profiles = new Set();
  const closures = new Set();
  for (const task of payload.tasks) {
    let taskUrl;
    try {
      taskUrl = new URL(task?.task_url);
    } catch {
      fail('Clerk returned an invalid Agent Task URL');
    }
    if (
      !['A', 'B'].includes(task?.label)
      || !CLOSURES.has(task?.closure)
      || !USER_ID.test(task?.user_id ?? '')
      || !PROFILE.test(task?.profile ?? '')
      || taskUrl.protocol !== 'https:'
      || taskUrl.username
      || taskUrl.password
      || taskUrl.hash
      || taskUrl.origin !== taskOrigin
    ) {
      fail('authenticated canary task identity is invalid');
    }
    labels.add(task.label);
    userIds.add(task.user_id);
    profiles.add(task.profile.toLowerCase());
    closures.add(task.closure);
  }
  if (
    labels.size !== 2
    || userIds.size !== 2
    || profiles.size !== 2
    || closures.size !== 2
  ) {
    fail('authenticated canary tasks are not isolated identities');
  }
  return {
    apiBase,
    appOrigin,
    sessionMaxDurationSeconds: payload.session_max_duration_seconds,
    tasks: payload.tasks,
  };
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
  sessionStartedAtMilliseconds,
  tokenExpiresAtSeconds,
  sessionMaxDurationSeconds,
) {
  if (
    !Number.isSafeInteger(sessionStartedAtMilliseconds)
    || sessionStartedAtMilliseconds <= 0
    || !Number.isSafeInteger(tokenExpiresAtSeconds)
    || !Number.isSafeInteger(sessionMaxDurationSeconds)
    || sessionMaxDurationSeconds !== EXPECTED_SESSION_MAX_DURATION_SECONDS
  ) {
    fail('authenticated canary expiry inputs are invalid');
  }
  const tokenDeadline = (tokenExpiresAtSeconds + JWT_EXPIRY_GRACE_SECONDS) * 1000;
  const sessionDeadline = sessionStartedAtMilliseconds
    + ((sessionMaxDurationSeconds + SESSION_EXPIRY_GRACE_SECONDS) * 1000);
  const proofDeadline = Math.max(tokenDeadline, sessionDeadline);
  const maximumDeadline = sessionStartedAtMilliseconds
    + ((sessionMaxDurationSeconds + MAX_EXPIRY_OVERHEAD_SECONDS) * 1000);
  if (proofDeadline > maximumDeadline) {
    fail('Clerk JWT expiry exceeds the bounded Agent Task session');
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
  fail('Clerk did not establish an application session in time');
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

async function proveSessionExpiryClosure(
  page,
  context,
  apiBase,
  appOrigin,
  label,
  token,
  sessionStartedAtMilliseconds,
  tokenExpiresAtSeconds,
  sessionMaxDurationSeconds,
) {
  // Clerk refreshes short-lived cookie JWTs while the browser session is live.
  // Waiting past both the captured JWT exp and the Agent Task session ceiling
  // proves the backend expiry check and the frontend's eventual signed-out state.
  const proofDeadline = expiryProofDeadlineMilliseconds(
    sessionStartedAtMilliseconds,
    tokenExpiresAtSeconds,
    sessionMaxDurationSeconds,
  );
  const remainingMilliseconds = proofDeadline - Date.now();
  const maximumWaitMilliseconds = (
    sessionMaxDurationSeconds + MAX_EXPIRY_OVERHEAD_SECONDS
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
  await proveAnonymousPrivateBoundary(page, context, apiBase, appOrigin, label);
}

async function main() {
  const { tasksPath } = argumentsFromCommandLine();
  const taskContract = validateTasks(await readBoundedJson(tasksPath, 'task file'));

  const { chromium } = await import('playwright');
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
    for (let index = 0; index < taskContract.tasks.length; index += 1) {
      const task = taskContract.tasks[index];
      const other = taskContract.tasks[1 - index];
      const context = await browser.newContext({
        acceptDownloads: false,
        serviceWorkers: 'block',
      });
      let token;
      try {
        const page = await context.newPage();
        await page.goto(task.task_url, { waitUntil: 'domcontentloaded', timeout: 45_000 });
        await page.waitForURL(
          (url) => url.origin === taskContract.appOrigin
            && url.pathname === '/',
          { timeout: 45_000 },
        );
        token = await applicationSessionToken(page, context, taskContract.appOrigin);
        // The one-time Clerk handoff may take time. Starting the natural-expiry
        // proof only after the application can retrieve a token is
        // conservative: it cannot declare expiry while the bounded Agent Task
        // session is still live.
        const sessionEstablishedAtMilliseconds = Date.now();
        const session = decodeSession(token);
        if (session.userId !== task.user_id) {
          fail(`Clerk Agent Task resolved the wrong canary ${task.label} identity`);
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
        } else if (task.closure === 'session_expiry') {
          await proveSessionExpiryClosure(
            page,
            context,
            taskContract.apiBase,
            taskContract.appOrigin,
            `canary ${task.label}`,
            token,
            sessionEstablishedAtMilliseconds,
            session.expiresAtSeconds,
            taskContract.sessionMaxDurationSeconds,
          );
        } else {
          fail(`canary ${task.label} has an unsupported closure proof`);
        }
      } finally {
        token = undefined;
        await context.clearCookies();
        await context.close();
      }
    }
  } finally {
    if (browser) {
      await browser.close();
    }
  }
  process.stdout.write(
    'authenticated production canary passed: two-user isolation, sign-out, and natural expiry proven\n',
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
