import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * Two traits can carry the same average rating and be liked at wildly different
 * rates. The score alone cannot separate them, so the like rate travels with it
 * along with the sample it was taken over.
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

test('a trait carries its like rate with the films behind it', async ({ page }) => {
  await page.goto('/people?tab=two');

  const panel = page
    .locator('.terminal-root section')
    .filter({ hasText: 'STRONGEST SHARED AFFINITIES' })
    .first();

  await expect(panel).toContainText('33% liked');
  await expect(panel).toContainText('of 57');
  await expect(panel).toContainText('13% liked');
  await expect(panel).toContainText('of 312');
});

test('two traits with the same rating are separated by how often they are liked', async ({
  page,
}) => {
  await page.goto('/people?tab=two');

  const panel = page
    .locator('.terminal-root section')
    .filter({ hasText: 'STRONGEST SHARED AFFINITIES' })
    .first();

  // Music and Animation sit within a hundredth of a star of each other; only
  // the like rate tells them apart.
  await expect(panel).toContainText('Music');
  await expect(panel).toContainText('Animation');
  await expect(panel).toContainText('33% liked');
  await expect(panel).toContainText('13% liked');
});
