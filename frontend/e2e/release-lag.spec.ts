import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * A film's decade says when it was made, never when this person got to it.
 * Someone whose library is entirely 2020s films could be following new releases
 * or working three years behind, and a decade breakdown renders both
 * identically.
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

test('the panel reports the typical wait with the films it measured', async ({ page }) => {
  await page.goto('/people?tab=one&subject=alpha');

  const panel = page.locator('section', { hasText: 'HOW SOON AFTER RELEASE' }).first();
  await expect(panel).toBeVisible();

  // 612 days reads as years, not as a four-digit day count.
  await expect(panel).toContainText('1.7 years');
  await expect(panel).toContainText('467 films with a known release date');
  await expect(panel).toContainText('WITHIN A MONTH OF RELEASE');
  await expect(panel).toContainText('AT LEAST FIVE YEARS OLD');
});

test('entries dated before release are declared rather than silently dropped', async ({ page }) => {
  await page.goto('/people?tab=one&subject=alpha');

  const panel = page.locator('section', { hasText: 'HOW SOON AFTER RELEASE' }).first();
  await expect(panel).toContainText('2 entries were dated before release and left out');
});
