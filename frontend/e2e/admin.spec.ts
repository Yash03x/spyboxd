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
