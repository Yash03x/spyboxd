import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * The circle answers two questions at once: what one person's ring looks like,
 * and how the whole group ranks. The redesign keeps both on the same tab rather
 * than swapping one for the other, so centring somebody no longer costs you the
 * group view.
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

test('the leaderboard answers the whole-group view', async ({ page }) => {
  await page.goto('/people?tab=circle&subject=alpha');

  await expect(page.getByText('▸ MOST CONNECTED', { exact: false })).toBeVisible();
});

test('centring a profile shows that profile\'s own connections', async ({ page }) => {
  await page.goto('/people?tab=circle&subject=alpha');

  const graph = page.locator('section', { hasText: 'FOLLOW GRAPH' }).first();
  await graph.getByRole('link', { name: '@bravo', exact: true }).first().click();

  await expect(page.getByText('▸ FOLLOW GRAPH · @BRAVO', { exact: false })).toBeVisible();
  // The group leaderboard stays: re-centring is a change of subject, not a
  // change of what the tab is for.
  await expect(page.getByText('▸ MOST CONNECTED', { exact: false })).toBeVisible();
});

test('the three edge kinds are named rather than counted by eye', async ({ page }) => {
  await page.goto('/people?tab=circle&subject=alpha');

  const graph = page.locator('section', { hasText: 'FOLLOW GRAPH' }).first();
  await expect(graph.getByText('MUTUAL', { exact: true })).toBeVisible();
  await expect(graph.getByText('ONE WAY', { exact: true })).toBeVisible();
  // An account the group orbits that we hold no data for is a third state, and
  // drawing it like a one-way follow would claim data we do not have.
  await expect(graph.getByText('NOT TRACKED', { exact: true })).toBeVisible();
});
