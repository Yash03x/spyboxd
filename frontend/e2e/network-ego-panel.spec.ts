import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * While one profile is centred, the panel underneath used to show the group's
 * "most connected" leaderboard with that profile's rank highlighted — a fact
 * about the whole group, asked while looking at one person.
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

test('the leaderboard answers the whole-group view', async ({ page }) => {
  await page.goto('/network');

  await expect(page.getByRole('heading', { name: /Most connected/i })).toBeVisible();
});

test('centring a profile replaces it with that profile\'s own connections', async ({ page }) => {
  await page.goto('/network');

  await page.getByRole('button', { name: /^Centre the network on @/ }).first().click();

  const heading = page.getByRole('heading', { name: /connections/i });
  await expect(heading).toBeVisible();
  await expect(page.getByRole('heading', { name: /Most connected/i })).toHaveCount(0);

  // The three directions the graph draws, named rather than counted by eye.
  const panel = page.locator('section').filter({ has: heading });
  // Each label shares its element with a count, so match on the label text.
  await expect(panel.getByText(/^Mutual/)).toBeVisible();
  await expect(panel.getByText(/^They follow/)).toBeVisible();
  await expect(panel.getByText(/^Follow them/)).toBeVisible();
});

test('returning to the full view brings the leaderboard back', async ({ page }) => {
  await page.goto('/network');
  await page.getByRole('button', { name: /^Centre the network on @/ }).first().click();
  await expect(page.getByRole('heading', { name: /connections/i })).toBeVisible();

  await page.getByRole('button', { name: /Back to full network/i }).click();

  await expect(page.getByRole('heading', { name: /Most connected/i })).toBeVisible();
});
