import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * The My Profiles card offered a control labelled "Follow graph" that expanded
 * a tabbed list of following/followers. No graph was ever drawn there; the
 * graph lives on the Network page.
 */
// The control sits in the admin view of the profile card.
test.beforeEach(async ({ page }) => {
  await installApiMocks(page, { isAdmin: true });
});

test('the profiles card offers a follows list, not a graph', async ({ page }) => {
  await page.goto('/profiles');

  // The button's accessible name comes from its aria-label; the visible text is
  // checked separately.
  const toggle = page.getByRole('button', { name: /follows and is followed by/i }).first();
  await expect(toggle).toBeVisible();
  await expect(toggle).toContainText('Following');
  // The old label promised something this panel never rendered.
  await expect(page.getByRole('button', { name: /follow graph for/i })).toHaveCount(0);
});

test('the follows panel links to the real graph, centred on that profile', async ({ page }) => {
  await page.goto('/profiles');

  await page.getByRole('button', { name: /follows and is followed by/i }).first().click();

  const link = page.getByRole('link', { name: /in the network graph/i }).first();
  await expect(link).toBeVisible();
  const href = await link.getAttribute('href');
  expect(href).toMatch(/^\/people\?tab=circle&subject=/);

  await link.click();
  await expect(page).toHaveURL(/\/people\?tab=circle&subject=/);
});
