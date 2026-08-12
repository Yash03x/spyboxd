import { expect, test } from '@playwright/test';

import { installApiMocks, profiles } from './fixtures/api';

test('backend admin truth exposes management and the residential sync queue', async ({ page }) => {
  await installApiMocks(page, { isAdmin: true });

  await page.goto('/data?tab=profiles');

  const queue = page.locator('.terminal-root section', { hasText: 'ADMIN · REQUEST QUEUE' }).first();
  await expect(queue).toBeVisible();
  await expect(queue.getByText('@queuedprofile', { exact: true })).toBeVisible();
  await expect(queue.getByText('accepted', { exact: true })).toBeVisible();
  await expect(
    page.locator('.terminal-root section', { hasText: 'ADMIN · ADD A PLACEHOLDER' }).first(),
  ).toBeVisible();
});

test('the request queue names the requester rather than printing a Clerk id', async ({ page }) => {
  await installApiMocks(page, { isAdmin: true });

  await page.goto('/data?tab=profiles');

  // Scoped to the admin queue: the same username also appears in the ordinary
  // request-status panel, which deliberately carries no requester line at all.
  const queue = page.locator('.terminal-root section', { hasText: 'ADMIN · REQUEST QUEUE' }).first();
  await expect(queue.getByText(/asked by @e2erequester/).first()).toBeVisible();
  // The opaque id is what an admin was reading before, and it must not be what
  // they read when a linked account exists.
  await expect(queue).not.toContainText('user_e2e');
});

test('admin can upload residential full-sync bundles without owner-export publishing consent', async ({ page }) => {
  await installApiMocks(page, { isAdmin: true });

  await page.goto('/data?tab=profiles');
  const uploadPanel = page.getByTestId('residential-sync-upload');
  await expect(uploadPanel).toBeVisible();
  const residentialPanel = page
    .locator('.terminal-root section', { hasText: 'ADMIN · RESIDENTIAL SYNC INTAKE' })
    .first();
  await expect(residentialPanel.getByText('Owner-export publishing stays off on this path.')).toBeVisible();

  const uploadRequestPromise = page.waitForRequest((request) => (
    new URL(request.url()).pathname === '/upload/' && request.method() === 'POST'
  ));
  await uploadPanel.getByLabel('Residential full-sync ZIP bundles').setInputFiles([
    { name: 'alpha.zip', mimeType: 'application/zip', buffer: Buffer.from('alpha fixture') },
    { name: 'bravo.zip', mimeType: 'application/zip', buffer: Buffer.from('bravo fixture') },
  ]);
  await expect(uploadPanel.getByText('2 ZIPs selected')).toBeVisible();
  await uploadPanel.getByRole('button', { name: 'IMPORT FULL SYNC' }).click();

  const uploadRequest = await uploadRequestPromise;
  const uploadBody = uploadRequest.postData() ?? '';
  expect(uploadBody).toContain('filename="alpha.zip"');
  expect(uploadBody).toContain('filename="bravo.zip"');
  expect(uploadBody).toContain('name="publish_owner_data"');
  expect(uploadBody).toMatch(/name="publish_owner_data"\r\n\r\nfalse\r\n/);
  expect(uploadBody).toContain('name="require_full_sync"');
  expect(uploadBody).toMatch(/name="require_full_sync"\r\n\r\ntrue\r\n/);
  await expect(page.getByText('2 bundles imported. Provenance: full_html_upload.')).toBeVisible();
  await expect(residentialPanel.getByText('A successful upload fulfills matching approved profile requests.')).toBeVisible();
});

test('residential bundle upload is not rendered for non-admin users', async ({ page }) => {
  await installApiMocks(page, { isAdmin: false });

  await page.goto('/data?tab=profiles');

  await expect(page.getByTestId('residential-sync-upload')).toHaveCount(0);
  await expect(page.getByText('ADMIN · RESIDENTIAL SYNC INTAKE')).toHaveCount(0);
  await expect(page.getByText('ADMIN · OWNER EXPORT INTAKE')).toHaveCount(0);
  await expect(page.getByText('ADMIN · REQUEST QUEUE')).toHaveCount(0);
  await expect(page.getByText('ADMIN · ADD A PLACEHOLDER')).toHaveCount(0);
});

test('admin library mutations refresh the selectable profile catalog', async ({ page }) => {
  await installApiMocks(page, { isAdmin: true });
  let catalogRequestCount = 0;
  page.on('request', (request) => {
    if (new URL(request.url()).pathname === '/profiles/catalog') catalogRequestCount += 1;
  });

  await page.goto('/data?tab=profiles');
  await expect(page.getByTestId('profile-catalog-result-summary')).toBeVisible();
  const initialCatalogRequestCount = catalogRequestCount;
  // Deleting is a two-step arm-and-confirm in the catalog rows, not a browser
  // dialog: the first press arms the row, the second one deletes.
  await page.getByRole('button', { name: /^Delete profile / }).first().click();
  await page.getByRole('button', { name: /^Confirm deleting / }).first().click();

  await expect(page.getByText(/was deleted from the library\./)).toBeVisible();
  await expect.poll(() => catalogRequestCount).toBeGreaterThan(initialCatalogRequestCount);
});

test('an admin can switch between personal monitoring and the preserved global dashboard', async ({ page }) => {
  await installApiMocks(page, { isAdmin: true });

  await page.goto('/overview');

  // The scope lens sits in the status bar beside the counts it changes, and
  // the chip states which library those counts came from.
  const managed = page.getByText('MANAGED LIBRARY', { exact: false });
  const monitored = page.getByText('· MONITORED', { exact: false });

  await page.getByRole('button', { name: 'Global admin' }).click();
  await expect(managed).toBeVisible();
  await page.getByRole('button', { name: 'Monitored', exact: true }).click();
  await expect(monitored).toBeVisible();
  await page.getByRole('button', { name: 'Global admin' }).click();
  await expect(managed).toBeVisible();
});

test('switching to a one-profile monitored scope drops the old global selection', async ({ page }) => {
  await installApiMocks(page, { isAdmin: true });
  await page.route(/^http:\/\/(?:127\.0\.0\.1|localhost):8000\/profiles\/?$/, (route) => (
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ profiles }),
    })
  ));
  await page.route(/^http:\/\/(?:127\.0\.0\.1|localhost):8000\/profiles\/tracked$/, (route) => (
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ profiles: profiles.slice(0, 1) }),
    })
  ));

  const signalSelections: string[][] = [];
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (url.pathname === '/api/spy-signals') {
      signalSelections.push(url.searchParams.getAll('profiles'));
    }
  });

  await page.goto('/overlaps', { waitUntil: 'networkidle' });
  expect(signalSelections.at(-1)).toEqual(profiles.slice(0, 6).map((profile) => profile.username));
  const requestsBeforeSwitch = signalSelections.length;

  await page.getByRole('button', { name: 'Monitored', exact: true }).click();

  await expect(page.getByText('· MONITORED', { exact: false })).toBeVisible();
  await expect(page.getByText('@alpha', { exact: true })).toBeVisible();
  await expect(page.getByText('@bravo', { exact: true })).toHaveCount(0);
  await expect(page.getByText('Two profiles are needed', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('Shared Fixture Film', { exact: true })).toHaveCount(0);
  expect(signalSelections.slice(requestsBeforeSwitch)).toEqual([]);
});

test('the private workspace still loads when browser storage is denied', async ({ page }) => {
  await installApiMocks(page, { isAdmin: true });
  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  await page.addInitScript(() => {
    Storage.prototype.getItem = function getItem() {
      throw new DOMException('Storage blocked', 'SecurityError');
    };
  });

  await page.goto('/overview');

  await expect(page.getByRole('heading', { level: 1, name: 'Overview', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Global admin' })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByText('This section could not render', { exact: true })).toHaveCount(0);
  expect(pageErrors).toEqual([]);
});

test('the admin scope toggle appears on every analytics page and persists across pages', async ({ page }) => {
  await installApiMocks(page, { isAdmin: true });

  await page.goto('/overlaps');
  await expect(page.getByRole('button', { name: 'Global admin' })).toBeVisible();

  const trackedProfilesRequest = page.waitForRequest((request) => (
    new URL(request.url()).pathname === '/profiles/tracked'
  ));
  await page.getByRole('button', { name: 'Monitored', exact: true }).click();
  await trackedProfilesRequest;

  for (const path of ['/analysis', '/compare', '/watch-together', '/overview', '/overlaps']) {
    await page.goto(path);
    await expect(page.getByRole('button', { name: 'Monitored', exact: true })).toHaveAttribute('aria-pressed', 'true');
  }
});

test('the scope toggle never renders for non-admin users', async ({ page }) => {
  await installApiMocks(page, { isAdmin: false });

  for (const path of ['/overview', '/overlaps', '/analysis', '/compare', '/watch-together']) {
    await page.goto(path);
    await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible();
    await expect(page.getByRole('button', { name: 'Global admin' })).toHaveCount(0);
  }
});
