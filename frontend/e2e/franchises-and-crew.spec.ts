import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * TMDB has stored collections and the whole crew since enrichment began, and
 * nothing read them. Both are counted over films *held*: the collection's real
 * size is not in the film payload, so any completion score would be invented.
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

test('series are counted as films held, not as a completion score', async ({ page }) => {
  await page.goto('/people?tab=one&subject=alpha');

  const panel = page.locator('section', { hasText: 'SERIES WORKED THROUGH' }).first();
  await expect(panel).toContainText('Harry Potter Collection');
  await expect(panel).toContainText('11');
  await expect(panel).not.toContainText('of 8');
  await expect(panel).toContainText('not a completion score');
});

test('an unrated series shows no average rather than zero', async ({ page }) => {
  await page.goto('/people?tab=one&subject=alpha');

  const panel = page.locator('section', { hasText: 'SERIES WORKED THROUGH' }).first();
  const row = panel.locator('div').filter({ hasText: 'X-Men Collection' }).last();
  await expect(row).toBeVisible();
  await expect(row).not.toContainText('0.0');
  await expect(row).toContainText('—');
});

test('the crew beyond the big three is listed', async ({ page }) => {
  await page.goto('/people?tab=one&subject=alpha');

  const panel = page.locator('section', { hasText: 'THE CREW BEYOND THE BIG THREE' }).first();
  for (const role of ['Composer', 'Cinematographer', 'Editor', 'Writer']) {
    await expect(panel).toContainText(role);
  }
});
