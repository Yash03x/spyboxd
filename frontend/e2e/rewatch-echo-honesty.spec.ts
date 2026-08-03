import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * Gap echoes split three ways: the later watcher followed the earlier one, they
 * demonstrably did not, or no authoritative follow import covers the pair. The
 * panel reported the first and the third. The second — checked, and no follow
 * found — was computed and never said, which lets a reader treat the remainder
 * as undisclosed rather than as ruled out.
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

test('the echo note accounts for every gap echo, including the ones ruled out', async ({ page }) => {
  await page.goto('/overlaps?tab=echoes');

  const note = page.getByText(/A follow marker appears on/);
  await expect(note).toBeVisible();
  await expect(note).toContainText('1 of the 3 echoes');
  // The evidence against, stated rather than left to subtraction.
  await expect(note).toContainText('1 were checked and carry no follow in either direction');
  await expect(note).toContainText('1 stay undetermined');
  // And why they stay that way, which the count alone does not say.
  await expect(note).toContainText('1 of 2 selected profiles have an authoritative');
});
