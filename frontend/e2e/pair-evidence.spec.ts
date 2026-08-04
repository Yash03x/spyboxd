import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * A star-gap claim needs enough shared ratings behind it. The fixture carries
 * two pairs: alpha+bravo agreeing within 0.30 across 35 shared ratings, and
 * alpha+delta at a perfect 0.00 built on ONE. Sorted raw, the coincidence
 * wins every "closest" crown — which is what production did: the closest pair
 * on Overview rested on three shared ratings while the copy attributed the
 * agreement to 89 shared films.
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page, { isAdmin: true });
});

test('a one-rating coincidence never wins closest pair on Overview', async ({ page }) => {
  await page.goto('/overview');

  const grid = page.locator('.terminal-root section', { hasText: 'WHO WATCHES WITH WHOM' }).first();
  // The measured pair wins, and the copy names both denominators: the ratings
  // the gap was computed over and the films merely shared.
  await expect(grid).toContainText('alpha and bravo are the closest pair');
  await expect(grid).toContainText('across 35 shared ratings, on 42 shared films');
  await expect(grid).not.toContainText('alpha and delta are the closest pair');
});

test('the tightest-pair table shows the ratings the gap rests on, not just shared films', async ({
  page,
}) => {
  await page.goto('/overlaps?tab=together');

  const panel = page
    .locator('.terminal-root section', { hasText: 'CLOSEST PAIR · WIDEST DISAGREEMENT' })
    .first();
  await expect(panel).toContainText('35 of 42');
  // The thin pair is filtered out of the ranking entirely.
  await expect(panel).not.toContainText('@alpha + @delta');
});

test('the leaderboard dashes a gap too thin to measure instead of printing 0.00', async ({
  page,
}) => {
  await page.goto('/overlaps?tab=together');

  const board = page.locator('.terminal-root section', { hasText: 'PAIR LEADERBOARD' }).first();
  // The thin pair still appears — its shared-film count is real — but its gap
  // is a dash, not a fabricated perfect agreement.
  await expect(board).toContainText('alpha + delta');
  const text = await board.innerText();
  const deltaRow = text.split('\n').slice(text.split('\n').findIndex((line) => line.includes('alpha + delta')));
  expect(deltaRow.slice(0, 4).join(' ')).toContain('—');
  expect(deltaRow.slice(0, 4).join(' ')).not.toContain('0.00');
});
