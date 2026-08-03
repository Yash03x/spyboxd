import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * Watching the same director twice inside a fortnight is a habit, not a
 * by-product of watching a lot. The span is what separates the two: seven films
 * over eight days is a run; the same seven across two years is a filmography.
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

test('the longest director run is named with its films and span', async ({ page }) => {
  await page.goto('/people?tab=one&subject=alpha');

  const panel = page.locator('section', { hasText: 'FILMOGRAPHY RUNS' }).first();
  await expect(panel).toBeVisible();

  await expect(panel).toContainText('Steven Soderbergh');
  await expect(panel).toContainText('over 8 days');
  await expect(panel).toContainText('Black Bag');
  await expect(panel).toContainText('4 stretches of three or more inside a fortnight');
});

test('a run is a count of films held, never a completion score', async ({ page }) => {
  await page.goto('/people?tab=one&subject=alpha');

  const panel = page.locator('section', { hasText: 'FILMOGRAPHY RUNS' }).first();
  // TMDB does not give a filmography's size in the film payload, so a
  // denominator here would be invented.
  await expect(panel).toContainText('never as a completion score');
});
