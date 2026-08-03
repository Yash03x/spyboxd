import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * Two claims the results panel used to make that its data did not support: a
 * candidate count above a list that rendered fewer rows, and an explanation
 * panel headed "Why this ranked first" for whichever row was clicked.
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

test('every ranked candidate is rendered, not just the first twenty', async ({ page }) => {
  await page.goto('/tonight?tab=picks');

  const panel = page.locator('.terminal-root section', { hasText: "TONIGHT'S SHORTLIST" }).first();
  await expect(panel).toBeVisible();
  await expect(panel).toContainText('RANKED CANDIDATES');

  const claimed = Number(
    (await panel.innerText()).match(/(\d+)\s*\n?\s*RANKED CANDIDATES/i)?.[1] ?? '0',
  );
  expect(claimed).toBeGreaterThan(0);

  // Each candidate row is a link into the explanation panel.
  const rows = panel.getByRole('link');
  await expect.poll(() => rows.count()).toBeGreaterThanOrEqual(claimed);
});

test('the explanation panel names the film rather than claiming it ranked first', async ({ page }) => {
  await page.goto('/tonight?tab=picks');

  const shortlist = page.locator('.terminal-root section', { hasText: "TONIGHT'S SHORTLIST" }).first();
  await shortlist.getByRole('link').first().click();

  await expect(page.getByText('WHY THIS RANKED FIRST', { exact: false })).toHaveCount(0);
  await expect(page.getByText(/▸ WHY .+ FITS/)).toBeVisible();
});
