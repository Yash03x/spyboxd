import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * Liking a film is a separate act from rating it, and the average hides the
 * difference: across the tracked library Music and Animation carry almost the
 * same average rating (3.46 against 3.44) while Music is liked two and a half
 * times as often. `like_rate` was computed for every trait and shown nowhere.
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

test('a trait carries its like rate with the films behind it', async ({ page }) => {
  await page.goto('/compare?tab=taste');

  const panel = page.getByRole('heading', { name: 'Strongest shared affinities' }).locator('..').locator('..');
  // The denominator matters: a like rate over 57 films and over 3 are not the
  // same claim, and the panel states which it is.
  await expect(panel).toContainText('33% liked of 57');
  await expect(panel).toContainText('13% liked of 312');
});

test('two traits with the same rating are separated by how often they are liked', async ({ page }) => {
  await page.goto('/compare?tab=taste');

  const panel = page.getByRole('heading', { name: 'Strongest shared affinities' }).locator('..').locator('..');
  await expect(panel).toContainText('33% liked');
  await expect(panel).toContainText('13% liked');
});
