import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * A film almost nobody has seen and a film everybody argues about are different
 * kinds of unusual, and an audience-size measure collapses them into one. The
 * spread of the crowd's own histogram separates them.
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

test('the panel reports how often the crowd was divided, with its denominator', async ({ page }) => {
  await page.goto('/people?tab=one&subject=alpha');

  const panel = page.locator('section', { hasText: 'WHERE THE CROWD WAS DIVIDED' }).first();
  await expect(panel).toBeVisible();

  await expect(panel).toContainText('86');
  await expect(panel).toContainText('47');
  // Stated, not implied: a share is meaningless without knowing how many films
  // carried a histogram at all.
  await expect(panel).toContainText('706 films with a readable histogram');
});

test('a lean toward contested films is named rather than left as a bare ratio', async ({ page }) => {
  await page.goto('/people?tab=one&subject=alpha');

  const panel = page.locator('section', { hasText: 'WHERE THE CROWD WAS DIVIDED' }).first();
  await expect(panel).toContainText('THEY SEEK OUT THE ARGUMENTS');
  await expect(panel).toContainText('Divisive Fixture Film');
});
