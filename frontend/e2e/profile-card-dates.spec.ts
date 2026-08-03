import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * Letterboxd publishes no join date on a public profile page — it exists only
 * in an account's own export — so every scraped profile used to read
 * "Member Since: Unknown". The first diary entry answers the same question and
 * we hold it for everyone.
 *
 * The redesign moved this from a profile card to a column on Overview's
 * "everyone we are watching" table. The guarantee is unchanged: a real date we
 * hold, labelled for what it is, never a join date we would have to invent.
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page, { isAdmin: true });
});

test('the roster shows when each profile started logging', async ({ page }) => {
  await page.goto('/overview');

  const roster = page.locator('section', { hasText: 'EVERYONE WE ARE WATCHING' }).first();
  await expect(roster.getByText('SINCE', { exact: true })).toBeVisible();

  // A real year from the diary, never the old "Unknown" placeholder for a
  // profile whose history we actually hold.
  await expect(roster.getByText('Unknown', { exact: true })).toHaveCount(0);
  await expect(roster.getByText(/^(19|20)\d\d$/).first()).toBeVisible();
});

test('the column says it is a diary date, not a join date', async ({ page }) => {
  await page.goto('/overview');

  await expect(
    page.getByText('SINCE is the earliest diary entry we hold, not a join date', { exact: false }),
  ).toBeVisible();
});

test('a profile with no dated history says so rather than showing a year', async ({ page }) => {
  await installApiMocks(page, { isAdmin: true, profileCount: 0 });
  await page.goto('/overview');

  // With nothing imported there is no year to show, and the panel says what
  // would fill it instead of rendering an empty table.
  await expect(page.getByRole('heading', { name: 'Choose your first monitored profile' })).toBeVisible();
});
