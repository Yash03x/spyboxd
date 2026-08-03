import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * "6 ranked candidates" says nothing on its own: six films nobody has queued
 * and six on everybody's list are different answers to the same question. The
 * count is qualified by what actually makes a pick work.
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

test('the candidate count is qualified by watchlist overlap and availability', async ({ page }) => {
  await page.goto('/tonight?tab=picks');

  const panel = page.locator('.terminal-root section', { hasText: "TONIGHT'S SHORTLIST" }).first();
  await expect(panel).toContainText('RANKED CANDIDATES');
  await expect(panel).toContainText("ON EVERYONE'S WATCHLIST");
  await expect(panel).toContainText('NOBODY HAS SEEN');
  await expect(panel).toContainText('STREAMING IN');
  // And the count is the length of the table, not a larger set it was cut from.
  await expect(panel).toContainText('rather than a larger set it was cut from');
  // And where the scan looked at more than it kept, it says how many.
  await expect(panel).toContainText('did not clear the filters above');
});
