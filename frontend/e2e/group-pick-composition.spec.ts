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
  // Subscription only, matching what Tonight › Leaving soon counts: the
  // payload also carries rent and buy offers, and calling those "streaming"
  // made the two tabs disagree about the same film.
  await expect(panel).toContainText('ON A SUBSCRIPTION IN');
  // And the count is the length of the table, not a larger set it was cut from.
  // The fixture's summary counts six candidates against two rendered, so
  // the truncation-aware branch must fire — the old copy claimed "never cut"
  // against a total that could not disagree with the table.
  await expect(panel).toContainText('6 candidates cleared the filters; the 2 below are the best fits');
});
