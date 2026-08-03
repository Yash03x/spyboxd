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

  // Both panels render a skeleton first, so every read here waits for the
  // classified row to arrive. Counting whatever is on screen the instant
  // navigation resolves measured the skeleton, not the tier.
  const roster = page.locator('.terminal-root section', { hasText: 'EVERYONE WE ARE WATCHING' }).first();
  await expect(roster.getByText('Full diary imported').first()).toBeVisible();

  await page.goto('/overlaps?tab=sure');
  const tiers = page.locator('.terminal-root section', { hasText: 'HOW SURE WE ARE' }).first();
  await expect(tiers.getByText('One date per film only')).toBeVisible();

  // The top tier must carry events, not zero, whenever the roster says a
  // profile has a full diary.
  const text = await tiers.innerText();
  const row = text.match(/Full diary imported\s+([\d,]+)\s+(\d+)%/);
  expect(row, `no top-tier row in:\n${text}`).not.toBeNull();
  expect(Number(row![1].replace(/,/g, ''))).toBeGreaterThan(0);
  expect(Number(row![2])).toBeGreaterThan(0);
});

test('the bottom tier says what it actually mixes together', async ({ page }) => {
  await page.goto('/overlaps?tab=sure');

  const tiers = page.locator('.terminal-root section', { hasText: 'HOW SURE WE ARE' }).first();
  // It is the difference between Letterboxd's stated total and our dated
  // events, so calling it "no date at all" overstated what we know.
  await expect(tiers).toContainText('No dated event');
  await expect(tiers).toContainText('rows we never imported at all');
});
