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

  await page.goto('/dashboard');

  await expect(page.getByText('Analytics across the complete managed profile library')).toBeVisible();
  await page.getByRole('button', { name: 'Monitored', exact: true }).click();
  await expect(page.getByText('Analytics across the Letterboxd profiles you monitor')).toBeVisible();
  await page.getByRole('button', { name: 'Global admin' }).click();
  await expect(page.getByText('Analytics across the complete managed profile library')).toBeVisible();
  await expect(page.getByText('Managed Profiles', { exact: true }).first()).toBeVisible();
});
