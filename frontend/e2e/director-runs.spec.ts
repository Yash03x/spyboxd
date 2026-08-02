import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * Watching the same director twice inside a fortnight happens about three times
 * more often than chance allows — measured by shuffling the dates while keeping
 * the films, so both date-clustering and library size are controlled for. It is
 * a habit, not a by-product of watching a lot, and nothing surfaced it.
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

test('the longest director run is named with its films and span', async ({ page }) => {
  await page.goto('/analysis');

  const heading = page.getByRole('heading', { name: 'Director runs' });
  await expect(heading).toBeVisible();

  const panel = heading.locator('..').locator('..');
  await expect(panel).toContainText('7 Steven Soderbergh films');
  await expect(panel).toContainText('over 8 days');
  await expect(panel).toContainText('Black Bag');
  await expect(panel).toContainText('4 stretches of three or more inside a fortnight');
});
