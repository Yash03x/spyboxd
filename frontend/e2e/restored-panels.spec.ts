import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * Eight panels v3 rendered were silently dropped by the redesign handoff,
 * despite its own "nothing in the current product is dropped" promise — the
 * API computed and shipped every field the whole time. Restored, and pinned
 * here so a future redesign cannot lose them silently again.
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page, { isAdmin: true });
});

test('One person renders actors, studios, languages and review years again', async ({ page }) => {
  await page.goto('/people?tab=one');

  for (const title of [
    'THE FACES THEY KEEP SEEING',
    'THE STUDIOS BEHIND IT',
    'WHAT LANGUAGE THE FILMS SPEAK',
    'REVIEWS, YEAR BY YEAR',
  ]) {
    await expect(
      page.locator('.terminal-root section', { hasText: title }).first(),
    ).toBeVisible();
  }
  // Fixture data flows through: Ghibli is the top studio.
  await expect(
    page.locator('.terminal-root section', { hasText: 'THE STUDIOS BEHIND IT' }).first(),
  ).toContainText('Studio Ghibli');
});

test('Together renders the three group lists again', async ({ page }) => {
  await page.goto('/overlaps?tab=together');

  for (const title of ["EVERYONE'S SEEN IT", 'AGREED ON, AND LIKED', 'SPLIT THE ROOM']) {
    await expect(
      page.locator('.terminal-root section', { hasText: title }).first(),
    ).toBeVisible();
  }
});

test('Echoes renders follow paths again, directional and caveated', async ({ page }) => {
  await page.goto('/overlaps?tab=echoes');

  const panel = page
    .locator('.terminal-root section', { hasText: 'WHO FOLLOWS WHOSE LEAD' })
    .first();
  await expect(panel).toContainText('@alpha → @bravo');
  // Correlation, never causation — the caveat says so in words.
  await expect(panel).toContainText('A pattern is not a cause');
});
