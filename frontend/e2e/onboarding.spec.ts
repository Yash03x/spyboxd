import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

test('an empty profile set guides the user to My Profiles', async ({ page }) => {
  await installApiMocks(page, { profileCount: 0 });

  await page.goto('/');

  await expect(page.getByRole('heading', { name: 'Choose your first profile' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Add or request a profile' })).toBeVisible();
});

test('one tracked profile explains how to unlock pair features', async ({ page }) => {
  await installApiMocks(page, { profileCount: 1 });

  await page.goto('/');

  await expect(page.getByRole('heading', { name: 'Add one more profile for Spy Signals' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Add or request a profile' })).toBeVisible();
});
