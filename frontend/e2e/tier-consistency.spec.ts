import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * Overview's roster and Overlaps › How sure classify the same profiles into the
 * same three tiers. They read one shared function so they cannot disagree —
 * before that they did: How sure derived its tier from the coverage endpoint's
 * `status`, which is never "complete" while any watch is undated, so it
 * reported nobody with a full diary while the roster reported almost everybody.
 *
 * Two panels contradicting each other about the same profiles is worse than
 * either being wrong on its own, so the agreement is pinned here rather than
 * left to whoever edits one of them next.
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page, { isAdmin: true });
});

test('a profile with a full diary is counted as one in both panels', async ({ page }) => {
  await page.goto('/overview');

  const roster = page.locator('.terminal-root section', { hasText: 'EVERYONE WE ARE WATCHING' }).first();
  const rosterFull = await roster.getByText('Full diary imported').count();
  expect(rosterFull).toBeGreaterThan(0);

  await page.goto('/overlaps?tab=sure');
  const tiers = page.locator('.terminal-root section', { hasText: 'HOW SURE WE ARE' }).first();
  await expect(tiers).toBeVisible();

  // The top tier must carry events, not zero, whenever the roster says a
  // profile has a full diary.
  const fullRow = tiers.locator('div').filter({ hasText: 'Full diary imported' }).last();
  const text = await fullRow.innerText();
  const share = Number(text.match(/(\d+)%/)?.[1] ?? '0');
  const events = Number((text.match(/([\d,]+)/)?.[1] ?? '0').replace(/,/g, ''));
  expect(events).toBeGreaterThan(0);
  expect(share).toBeGreaterThan(0);
});

test('the bottom tier says what it actually mixes together', async ({ page }) => {
  await page.goto('/overlaps?tab=sure');

  const tiers = page.locator('.terminal-root section', { hasText: 'HOW SURE WE ARE' }).first();
  // It is the difference between Letterboxd's stated total and our dated
  // events, so calling it "no date at all" overstated what we know.
  await expect(tiers).toContainText('No dated event');
  await expect(tiers).toContainText('rows we never imported at all');
});
