import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * The old profile manager offered a per-card "follows" drawer; no graph was
 * ever drawn there. The follow lists and the real graph both live in People ›
 * The circle now, so the roster's job is to take the reader there, centred on
 * the profile they picked.
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page, { isAdmin: true });
});

test('every synced-roster row links to the circle, centred on that profile', async ({ page }) => {
  await page.goto('/data?tab=profiles');

  const roster = page
    .locator('.terminal-root section', { hasText: 'EVERYONE WE HAVE SYNCED' })
    .first();
  const firstRow = roster.getByRole('link').first();
  await expect(firstRow).toBeVisible();
  const href = await firstRow.getAttribute('href');
  expect(href).toMatch(/^\/people\?tab=circle&subject=/);
  await expect(roster).toContainText('People › The circle');
});

test('following the roster link lands on the circle for that profile', async ({ page }) => {
  await page.goto('/data?tab=profiles');

  const roster = page
    .locator('.terminal-root section', { hasText: 'EVERYONE WE HAVE SYNCED' })
    .first();
  await roster.getByRole('link').first().click();

  await expect(page).toHaveURL(/\/people\?tab=circle&subject=/);
});
