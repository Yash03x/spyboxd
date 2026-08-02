import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * A film's average rating cannot say whether the crowd agreed about it: 3.0
 * from everybody and 3.0 from a room split between 0.5 and 5.0 are opposite
 * experiences flattened to the same number. Letterboxd publishes the histogram
 * behind that average and Spyboxd already stores it, so this panel asks the
 * question the average cannot.
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

test('the panel reports how often the crowd was divided, with its denominator', async ({ page }) => {
  await page.goto('/analysis');

  const heading = page.getByRole('heading', { name: 'Films the world argues about' });
  await expect(heading).toBeVisible();

  const panel = heading.locator('..').locator('..');
  await expect(panel).toContainText('86');
  await expect(panel).toContainText('47');
  // Stated, not implied: a share is meaningless without knowing how many films
  // carried a histogram at all.
  await expect(panel).toContainText('706 films with a readable histogram');
});

test('a lean toward contested films is named rather than left as a bare ratio', async ({ page }) => {
  await page.goto('/analysis');

  const panel = page
    .getByRole('heading', { name: 'Films the world argues about' })
    .locator('..')
    .locator('..');

  await expect(panel).toContainText('they seek out the arguments');
  await expect(panel).toContainText('Divisive Fixture Film');
});
