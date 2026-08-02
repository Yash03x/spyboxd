import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * TMDB names the franchise a film belongs to on 1,143 of the 4,554 enriched
 * films, and credits 732 distinct crew jobs. Spyboxd stored both and surfaced
 * neither the franchise nor any crew beyond composer, cinematographer and
 * editor — while Letterboxd's own stats page lists every one of them.
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

test('series are counted as films held, not as a completion score', async ({ page }) => {
  await page.goto('/analysis');

  const panel = page.getByRole('heading', { name: 'Series worked through' }).locator('..').locator('..');
  await expect(panel).toContainText('Harry Potter Collection');
  await expect(panel).toContainText('11');
  // TMDB does not give a collection's size in the film payload, so claiming
  // "8 of 8" would be inventing the denominator.
  await expect(panel).not.toContainText('of 8');
  await expect(panel).toContainText('not a completion score');
});

test('an unrated series shows no average rather than zero', async ({ page }) => {
  await page.goto('/analysis');

  const row = page.locator('li').filter({ hasText: 'X-Men Collection' }).first();
  await expect(row).toBeVisible();
  await expect(row).not.toContainText('0.0');
});

test('the crew beyond the big three is listed', async ({ page }) => {
  await page.goto('/analysis');

  const body = page.locator('body');
  for (const name of ['Kevin Feige', 'Stan Lee', 'David Koepp', 'Sarah Halley Finn']) {
    await expect(body).toContainText(name);
  }
});
