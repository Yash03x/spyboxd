import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * Letterboxd publishes no join date on a public profile page — it exists only
 * in an account's own export — so every scraped profile read
 * "Member Since: Unknown". The first diary entry answers the same question and
 * we hold it for everyone.
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page, { isAdmin: true });
});

test('a profile without a join date shows when it started logging', async ({ page }) => {
  await page.goto('/dashboard');

  await expect(page.getByText('Logging Since').first()).toBeVisible();
  // Never the old placeholder for a profile whose history we actually hold.
  await expect(page.getByText('Unknown', { exact: true })).toHaveCount(0);
});

test('a profile that does have a join date still says Member Since', async ({ page }) => {
  await page.goto('/dashboard');

  await expect(page.getByText('Member Since').first()).toBeVisible();
});

test('Investigate opens the changed profile, not the co-watch scanner', async ({ page }) => {
  await page.goto('/dashboard');

  const investigate = page.getByRole('button', { name: /^Investigate/ });
  await expect(investigate).toBeVisible();
  await investigate.click();

  // It used to push to /spy-signals — the same place as the button beside it,
  // and a different question from "what did this profile just do".
  await expect(page).toHaveURL(/\/analysis/);
});
