import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * The group-pick summary already counts how many candidates sit on every
 * selected watchlist and how many can actually be streamed in the chosen
 * region. Both reached the browser and neither was shown, so the header said
 * "6 ranked candidates" and left the reader to assume all six were
 * watchable tonight. Availability is the figure that changes a decision.
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

test('the candidate count is qualified by watchlist overlap and availability', async ({ page }) => {
  await page.goto('/watch-together');

  const header = page.getByText('6 ranked candidates');
  await expect(header).toBeVisible();
  await expect(header).toContainText('2 on everyone’s watchlist');
  await expect(header).toContainText('3 streaming here');
});
