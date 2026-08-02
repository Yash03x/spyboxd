import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * "Who watched first?" is built from `influence_paths`, which needs an earlier
 * and a later watcher and therefore cannot contain a same-day co-watch. That is
 * correct for the question, but it makes the list shorter than the co-watch
 * count above it with no explanation — 98 co-watches against 78 rows for one
 * real pair, the difference being same-day viewings. Unstated, a missing row
 * reads as missing data rather than as a question that does not apply.
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

test('same-day co-watches are accounted for, not silently absent from the ranking', async ({ page }) => {
  await page.goto('/compare?tab=dossier');

  const panel = page.getByRole('heading', { name: 'Who watched first?' }).locator('..').locator('..');
  await expect(panel).toContainText('the same day, where neither of them was first');
});
