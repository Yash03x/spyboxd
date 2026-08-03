import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * A same-day co-watch has no leader, and dropping those rows silently makes the
 * remaining lead share look like it covers every shared film. They are counted
 * and named instead.
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

test('same-day co-watches are accounted for, not silently absent from the ranking', async ({
  page,
}) => {
  await page.goto('/people?tab=two');

  const panel = page.locator('.terminal-root section').filter({ hasText: 'HEAD TO HEAD' }).first();
  await expect(panel).toContainText('the same day, where neither of them was first');
});
