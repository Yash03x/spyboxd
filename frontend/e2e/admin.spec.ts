import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

test('backend admin truth exposes management and the residential sync queue', async ({ page }) => {
  await installApiMocks(page, { isAdmin: true });

  await page.goto('/profiles');

  await expect(page.getByRole('heading', { level: 1, name: 'Profiles', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Admin add placeholder' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Profile request queue' })).toBeVisible();
  await expect(page.getByText('@queuedprofile', { exact: true }).last()).toBeVisible();
  await expect(page.getByText('Awaiting residential sync', { exact: true })).toBeVisible();
});

test('the request queue names the requester rather than printing a Clerk id', async ({ page }) => {
  await installApiMocks(page, { isAdmin: true });

  await page.goto('/profiles');

  // Scoped to the admin queue: the same username also appears on the ordinary
  // request card, which deliberately carries no requester line at all.
  const queued = page.locator('article').filter({ hasText: 'Requester' }).first();
  await expect(queued).toContainText('Requester @e2erequester');
  // The opaque id is what an admin was reading before, and it must not be what
  // they read when a linked account exists.
  await expect(queued).not.toContainText('user_e2e');
});

test('admin can upload residential full-sync bundles without owner-export publishing consent', async ({ page }) => {
  await installApiMocks(page, { isAdmin: true });

  await page.goto('/profiles');
  const uploadPanel = page.getByTestId('residential-sync-upload');
  await expect(uploadPanel).toBeVisible();
  await expect(uploadPanel.getByText('Owner-export publishing stays off for this import.')).toBeVisible();

  const uploadRequestPromise = page.waitForRequest((request) => (
    new URL(request.url()).pathname === '/upload/' && request.method() === 'POST'
  ));
  await uploadPanel.getByLabel('Residential full-sync ZIP bundles').setInputFiles([
    { name: 'alpha.zip', mimeType: 'application/zip', buffer: Buffer.from('alpha fixture') },
    { name: 'bravo.zip', mimeType: 'application/zip', buffer: Buffer.from('bravo fixture') },
  ]);
  await expect(uploadPanel.getByText('2 ZIPs selected')).toBeVisible();
  await uploadPanel.getByRole('button', { name: 'Import full sync' }).click();

  const uploadRequest = await uploadRequestPromise;
  const uploadBody = uploadRequest.postData() ?? '';
  expect(uploadBody).toContain('filename="alpha.zip"');
  expect(uploadBody).toContain('filename="bravo.zip"');
  expect(uploadBody).toContain('name="publish_owner_data"');
  expect(uploadBody).toMatch(/name="publish_owner_data"\r\n\r\nfalse\r\n/);
  expect(uploadBody).toContain('name="require_full_sync"');
  expect(uploadBody).toMatch(/name="require_full_sync"\r\n\r\ntrue\r\n/);
  await expect(page.getByText('2 residential full-sync bundles imported. Provenance: full_html_upload.')).toBeVisible();
  await expect(uploadPanel.getByText('A successful upload fulfills matching approved profile requests.')).toBeVisible();
});

test('residential bundle upload is not rendered for non-admin users', async ({ page }) => {
  await installApiMocks(page, { isAdmin: false });

  await page.goto('/profiles');

  await expect(page.getByTestId('residential-sync-upload')).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Residential Sync Workflow' })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Optional owner-provided Letterboxd export' })).toHaveCount(0);
});

test('admin library mutations refresh the selectable profile catalog', async ({ page }) => {
  await installApiMocks(page, { isAdmin: true });
  page.on('dialog', (dialog) => dialog.accept());
  let catalogRequestCount = 0;
  page.on('request', (request) => {
    if (new URL(request.url()).pathname === '/profiles/catalog') catalogRequestCount += 1;
  });

  await page.goto('/profiles');
  await expect(page.getByTestId('profile-catalog-result-summary')).toBeVisible();
  const initialCatalogRequestCount = catalogRequestCount;
  await page.getByTestId('tracked-profile-grid').getByTitle('Delete profile').first().click();

  await expect(page.getByText('Profile deleted successfully.')).toBeVisible();
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
