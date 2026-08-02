import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * A film's decade says when it was made, never when this person got to it.
 * Someone whose library is entirely 2020s films could be following new releases
 * or working three years behind, and the existing decade breakdown renders both
 * identically. TMDB release dates and diary dates were both already stored.
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

test('the panel reports the typical wait with the films it measured', async ({ page }) => {
  await page.goto('/analysis');

  const heading = page.getByRole('heading', { name: 'How soon after release' });
  await expect(heading).toBeVisible();

  const panel = heading.locator('..').locator('..');
  // 612 days reads as years, not as a four-digit day count.
  await expect(panel).toContainText('1.7 years');
  await expect(panel).toContainText('467 films with a known release date');
  await expect(panel).toContainText('22% within a month of release');
  await expect(panel).toContainText('42% at least five years old');
});

test('entries dated before release are declared rather than silently dropped', async ({ page }) => {
  await page.goto('/analysis');

  const panel = page
    .getByRole('heading', { name: 'How soon after release' })
    .locator('..')
    .locator('..');

  await expect(panel).toContainText('2 entries were dated before release and left out');
});
