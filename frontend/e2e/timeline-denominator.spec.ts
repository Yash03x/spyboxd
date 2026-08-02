import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * The period line read "3.40 avg · 40 watches", which invites 40 to be read as
 * what the average rests on. It does not: `rated_events` is the denominator and
 * bravo rated 16 of those 40. The field was computed for every period and every
 * profile and rendered nowhere, while the number that is not the denominator
 * sat directly beside the average.
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

test('a period average states the rated films it rests on, not just the watches', async ({ page }) => {
  await page.goto('/compare?tab=timeline');

  const panel = page.locator('body');
  await expect(panel).toContainText('3.40 avg of 16 rated · 40 watches');
});

test('a profile who rated everything they watched is not given a redundant denominator', async ({ page }) => {
  await page.goto('/compare?tab=timeline');

  // alpha rated all 80: repeating the same number twice would be noise.
  await expect(page.locator('body')).toContainText('3.70 avg · 80 watches');
});
