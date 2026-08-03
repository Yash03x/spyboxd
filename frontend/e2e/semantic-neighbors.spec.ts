import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * A shared keyword is an abstraction; the films that produced it are the
 * evidence. Both sit in the same panel so a reader can check one against the
 * other rather than taking the abstraction on trust.
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

test('the shared-affinities panel names the films behind the traits', async ({ page }) => {
  await page.goto('/people?tab=two');

  const panel = page
    .locator('.terminal-root section')
    .filter({ hasText: 'STRONGEST SHARED AFFINITIES' })
    .first();
  await expect(panel).toBeVisible();

  await expect(panel.getByText('Decision to Leave', { exact: false })).toBeVisible();
  await expect(panel.getByText('Both watched a Park Chan-wook film')).toBeVisible();
  await expect(panel.getByText('Fallen Angels', { exact: false })).toBeVisible();
});
