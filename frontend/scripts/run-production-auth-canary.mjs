#!/usr/bin/env node

import { constants } from 'node:fs';
import { open } from 'node:fs/promises';
import { chromium } from 'playwright';

const MAX_FILE_BYTES = 64 * 1024;
const MAX_RESPONSE_BYTES = 2 * 1024 * 1024;
const USER_ID = /^user_[A-Za-z0-9]+$/;
const PROFILE = /^[A-Za-z0-9_]{2,15}$/;

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

function validateTasks(payload) {
  if (!payload || payload.version !== 1 || !Array.isArray(payload.tasks)) {
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
  for (const task of payload.tasks) {
    let taskUrl;
    try {
      taskUrl = new URL(task?.task_url);
    } catch {
      fail('Clerk returned an invalid Agent Task URL');
    }
    if (
      !['A', 'B'].includes(task?.label)
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
  }
  if (labels.size !== 2 || userIds.size !== 2 || profiles.size !== 2) {
    fail('authenticated canary tasks are not isolated identities');
  }
  return { apiBase, appOrigin, tasks: payload.tasks };
}

function decodeSession(token) {
  if (typeof token !== 'string' || token.length < 100 || token.split('.').length !== 3) {
    fail('Clerk did not establish a valid session token');
  }
  let payload;
  try {
    payload = JSON.parse(Buffer.from(token.split('.')[1], 'base64url').toString('utf8'));
  } catch {
    fail('Clerk returned an invalid session token');
  }
  if (!USER_ID.test(payload?.sub ?? '')) {
    fail('Clerk session token omitted its user identity');
  }
  return { userId: payload.sub };
}

async function sessionCookie(context, appOrigin, timeoutMilliseconds = 30_000) {
  const hostname = new URL(appOrigin).hostname;
  const deadline = Date.now() + timeoutMilliseconds;
  while (Date.now() < deadline) {
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
  const response = await context.request.get(`${apiBase}${path}`, {
    failOnStatusCode: false,
    headers: {
      Accept: 'application/json',
      Authorization: `Bearer ${token}`,
      'Cache-Control': 'no-cache',
    },
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

async function main() {
  const { tasksPath } = argumentsFromCommandLine();
  const taskContract = validateTasks(await readBoundedJson(tasksPath, 'task file'));

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
            && url.pathname === '/profiles'
            && !url.search
            && !url.hash,
          { timeout: 45_000 },
        );
        token = await sessionCookie(context, taskContract.appOrigin);
        const session = decodeSession(token);
        if (session.userId !== task.user_id) {
          fail(`Clerk Agent Task resolved the wrong canary ${task.label} identity`);
        }
        await page.getByRole('button', { name: 'Sign out', exact: true }).waitFor({
          state: 'visible',
          timeout: 30_000,
        });
        await validateIdentity(context, taskContract.apiBase, task, other, token);
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
  process.stdout.write('authenticated production canary passed: 2 browser sessions remained isolated\n');
}

main().catch((error) => {
  const detail = error instanceof CanaryError
    ? error.message
    : 'browser-backed isolation check failed';
  process.stderr.write(`authenticated production canary failed: ${detail}\n`);
  process.exitCode = 1;
});
