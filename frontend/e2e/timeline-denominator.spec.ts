import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * A period average is taken over rated events, not over watches, and those two
 * differ whenever somebody logs without rating. Printing the average beside the
 * watch count alone implies a denominator it never used.
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

test('a period average states the rated films it rests on, not just the watches', async ({
  page,
}) => {
  await page.goto('/people?tab=two');

  const panel = page.locator('.terminal-root section').filter({ hasText: 'HOW TASTE CHANGED' }).first();
  await expect(panel).toContainText('3.40 avg of 16 rated · 40 watches');
});

test('a profile who rated everything they watched is not given a redundant denominator', async ({
  page,
}) => {
  await page.goto('/people?tab=two');

  const panel = page.locator('.terminal-root section').filter({ hasText: 'HOW TASTE CHANGED' }).first();
  await expect(panel).toContainText('3.70 avg · 80 watches');
});
