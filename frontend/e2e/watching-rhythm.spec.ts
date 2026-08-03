import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * Volume says how much somebody watched; rhythm says how. The same film count
 * reads completely differently if it arrived weekly or in two binges either
 * side of a silence, and an average alone cannot tell those apart.
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

test('the watching rhythm panel renders the weekday breakdown it is given', async ({ page }) => {
  await page.goto('/people?tab=one&subject=alpha');

  const panel = page.locator('.terminal-root section').filter({ hasText: 'THEIR RHYTHM' }).first();
  await expect(panel).toBeVisible();

  for (const day of ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']) {
    await expect(panel.getByText(day, { exact: true }).last()).toBeVisible();
  }
  await expect(panel.getByText('123', { exact: true })).toBeVisible();
  await expect(panel).toContainText('MOST OFTEN A');
  await expect(panel).toContainText('Sat');
  await expect(panel).toContainText('301 days with an entry');
});

test('a long silence is named, since a run of quiet weeks is not the same as a slow one', async ({
  page,
}) => {
  await page.goto('/people?tab=one&subject=alpha');

  const panel = page.locator('.terminal-root section').filter({ hasText: 'THEIR RHYTHM' }).first();
  await expect(panel).toContainText('Longest silence: 41 days');
  await expect(panel).toContainText('2024-05-26');
});
