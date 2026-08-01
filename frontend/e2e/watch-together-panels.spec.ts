import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * Three claims the results panel used to make that its data did not support:
 * a "Where to watch" column naming rent/buy stores under a Streaming filter,
 * a candidate count above a list that rendered fewer rows, and an explanation
 * panel headed "Why this ranked first" for whichever row was clicked.
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

test('every ranked candidate is rendered, not just the first twenty', async ({ page }) => {
  await page.goto('/watch-together');

  const header = page.getByText(/ranked candidates/i).first();
  await expect(header).toBeVisible();
  const claimed = Number((await header.innerText()).match(/(\d+)\s+ranked/i)?.[1] ?? '0');
  expect(claimed).toBeGreaterThan(0);

  // The rows are buttons carrying a score ring; count the candidate rows.
  const rows = page.locator('[aria-pressed]');
  await expect.poll(() => rows.count()).toBeGreaterThanOrEqual(claimed);
});

test('the explanation panel names the film rather than claiming it ranked first', async ({ page }) => {
  await page.goto('/watch-together');

  const rows = page.locator('[aria-pressed]');
  await expect.poll(() => rows.count()).toBeGreaterThan(0);
  await rows.first().click();

  await expect(page.getByRole('heading', { name: /^Why this ranked first$/ })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: /^Why .+ fits$/ })).toBeVisible();
});
