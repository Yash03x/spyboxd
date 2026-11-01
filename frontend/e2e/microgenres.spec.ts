import { expect, test } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import { installApiMocks } from './fixtures/api';

test.beforeEach(async ({ page }) => { await installApiMocks(page); });

test('film microgenres show group evidence, filter and retain selection on reload', async ({ page }) => {
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  const movie = { movie_id: 901, title: 'Time Loop Example', year: 2020, poster_url: null };
  const trait = { id: 'microgenre:science fiction · time travel', label: 'Science Fiction · time travel', dimension: 'microgenre', unique_films: 3,
    sample_size: 4, average_rating: 4, per_profile: [{ username: 'alpha', sample_size: 3, rated_sample_size: 3 }, { username: 'bravo', sample_size: 1, rated_sample_size: 0 }],
    examples: [{ movie, watched_by: ['alpha'] }], top_movies: [] };
  await page.route('**/api/taste-dna?*', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({
    dimensions: { microgenre: [trait], theme: [{ ...trait, id: 'theme:time travel', label: 'time travel', dimension: 'theme' }] },
    trait_coverage: { microgenre: { films: 3, total_films: 5 } },
  }) }));
  await page.goto('/films?tab=microgenres&profiles=alpha&profiles=bravo');
  await expect(page.getByRole('button', { name: 'Science Fiction · time travel', exact: true })).toBeVisible();
  await expect(page.getByRole('region', { name: 'THE FILMS BEHIND THE CATEGORY' })).toContainText('Watched by @alpha');
  await page.getByRole('button', { name: 'Science Fiction · time travel', exact: true }).click();
  await page.reload();
  await expect(page.getByRole('button', { name: 'Science Fiction · time travel', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await page.getByLabel('Category type', { exact: true }).selectOption('theme');
  await expect(page.getByRole('button', { name: 'time travel', exact: true })).toBeVisible();
  await page.getByLabel('Search loaded categories', { exact: true }).fill('no match');
  await expect(page.getByRole('heading', { name: 'No matching categories yet' }).first()).toBeVisible();
  await page.getByLabel('Search loaded categories', { exact: true }).fill('');
  await expect(page.getByRole('button', { name: 'time travel', exact: true })).toBeVisible();
  expect(errors).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
});

test('anime themes and microgenres open exact watched evidence and export it', async ({ page }) => {
  await page.goto('/anime?tab=taste');
  const themes = page.getByRole('region', { name: 'THEMES & STORY ELEMENTS' });
  await expect(themes).toContainText('55 / 55');
  await themes.getByRole('link', { name: 'Coming of Age', exact: true }).click();
  await expect(page.getByLabel('Theme', { exact: true })).toHaveValue('Coming of Age');
  await expect(page.getByLabel('List scope')).toHaveValue('watched');
  await expect(page.getByText('1–50 of 55 titles', { exact: true })).toBeVisible();
  await page.goto('/anime?tab=taste');
  await page.getByRole('region', { name: 'YOUR ANIME MICROGENRES' }).getByRole('link', { name: 'Action · Coming of Age', exact: true }).click();
  await expect(page.getByLabel('Microgenre', { exact: true })).toHaveValue('Action · Coming of Age');
  await expect(page.getByText('1–28 of 28 titles', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText('1–28 of 28 titles', { exact: true })).toBeVisible();
  const downloaded = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export matching CSV' }).click();
  const csv = await readFile((await (await downloaded).path())!, 'utf8');
  expect(csv).toContain('"themes","microgenres","theme_source"');
  expect(csv).toContain('"Coming of Age","Action · Coming of Age","AniList"');
  expect(csv.split('\r\n').filter(Boolean)).toHaveLength(29);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
});
