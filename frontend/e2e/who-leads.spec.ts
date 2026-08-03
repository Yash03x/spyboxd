import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * Whoever watches more reaches a shared film first for no reason but volume, so
 * a bare "gets there first" share is not evidence of leading. The baseline it
 * has to beat is published beside it.
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

test('the leader is shown against the share of watching that would explain it', async ({ page }) => {
  await page.goto('/people?tab=two');

  const panel = page.locator('.terminal-root section').filter({ hasText: 'HEAD TO HEAD' }).first();
  await expect(panel).toBeVisible();

  await expect(panel).toContainText('64%');
  await expect(panel).toContainText('24%');
  await expect(panel).toContainText('they genuinely get there earlier');
  await expect(panel).toContainText('50 films they both dated, days apart');
});
