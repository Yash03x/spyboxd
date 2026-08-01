import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * The Compare page's "Semantic neighbors" panel shipped with a heading, a
 * promise ("contextual matches, not exact-title co-watches") and a backend that
 * returned a hard-coded empty list, so it was blank for every user from the
 * first commit onward. Assert it renders what it is given.
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

test('the semantic neighbors panel renders its entries', async ({ page }) => {
  await page.goto('/compare?tab=taste');

  const heading = page.getByRole('heading', { name: 'Semantic neighbors' });
  await expect(heading).toBeVisible();

  // The panel is a heading plus its cards; a heading alone is the bug.
  const panel = page.locator('section').filter({ has: heading });
  await expect(panel.getByText('Decision to Leave')).toBeVisible();
  await expect(panel.getByText('Both watched a Park Chan-wook film')).toBeVisible();
  await expect(panel.getByText('Fallen Angels')).toBeVisible();
});
