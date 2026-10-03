import { expect, test } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import { installApiMocks } from './fixtures/api';
import { animeFixture } from './fixtures/anime';

test.beforeEach(async ({ page }) => { await installApiMocks(page); });

test('Anime is a private parallel section with useful totals and no film scope', async ({ page }) => {
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto('/overview?profiles=alpha&profiles=bravo');
  await page.getByRole('link', { name: '07 Anime', exact: true }).click();
  await expect(page).toHaveURL(/\/anime$/);
  await expect(page.getByText('PRIVATE MAL EXPORT · YOUR ACCOUNT ONLY')).toBeVisible();
  await expect(page.getByText('anime_fixture · 65 titles')).toBeVisible();
  await expect(page.getByRole('region', { name: 'YOUR ANIME AT A GLANCE' })).toContainText('570');
  await expect(page.getByRole('region', { name: 'HOW YOU SCORE' })).toContainText('15');
  await expect(page.getByText('25 lack a full finish date.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Global admin', exact: true })).toHaveCount(0);
  expect(errors).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
});

test('status and score drilldowns survive reload, filter combinations and browser history', async ({ page }) => {
  await page.goto('/anime');
  await page.getByRole('region', { name: 'YOUR LIST, BY STATUS' }).getByRole('link', { name: 'Completed', exact: true }).click();
  await expect(page.getByLabel('Status', { exact: true })).toHaveValue('completed');
  await expect(page.getByText('1–45 of 45 titles', { exact: true })).toBeVisible();
  await page.getByLabel('Score', { exact: true }).selectOption('10');
  await page.getByRole('button', { name: 'Apply filters' }).click();
  await expect(page.getByText('1–9 of 9 titles', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByLabel('Score', { exact: true })).toHaveValue('10');
  await page.getByRole('link', { name: 'Clear filters' }).click();
  await expect(page.getByText('1–50 of 65 titles', { exact: true })).toBeVisible();
  await page.goBack();
  await expect(page.getByLabel('Score', { exact: true })).toHaveValue('10');
});

test('timeline shows measured coverage and exact year evidence', async ({ page }) => {
  await page.goto('/anime?tab=timeline');
  await expect(page.getByLabel('Timeline year')).toHaveValue('2025');
  await expect(page.getByRole('region', { name: 'START TO FINISH, HONESTLY' })).toContainText('31');
  await page.getByRole('region', { name: 'COMPLETIONS THROUGH THE YEARS' }).getByRole('link', { name: '2025', exact: true }).click();
  await expect(page.getByLabel('Completion year')).toHaveValue('2025');
  await expect(page.getByText('1–20 of 20 titles', { exact: true })).toBeVisible();
  await page.getByLabel('Completion year').selectOption('undated');
  await page.getByRole('button', { name: 'Apply filters' }).click();
  await expect(page.getByText('1–25 of 25 titles', { exact: true })).toBeVisible();
});

test('library paginates, searches and exports every matching row safely', async ({ page }) => {
  await page.goto('/anime?tab=library');
  await expect(page.getByText('1–50 of 65 titles', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await expect(page.getByText('51–65 of 65 titles', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText('51–65 of 65 titles', { exact: true })).toBeVisible();
  const downloaded = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export matching CSV' }).click();
  const download = await downloaded; const path = await download.path();
  const csv = await readFile(path!, 'utf8');
  expect(csv.split('\r\n').filter(Boolean)).toHaveLength(66);
  expect(csv).toContain('"\'=Formula, ""Anime"""');
  await expect(page.getByRole('status').filter({ hasText: 'Exported all 65' })).toBeVisible();
  await page.getByLabel('Title or MAL ID').fill('65');
  await page.getByRole('button', { name: 'Apply filters' }).click();
  await expect(page.getByText('1–1 of 1 titles', { exact: true })).toBeVisible();
  expect(new URL(page.url()).searchParams.has('anime_page')).toBe(false);
  await page.getByLabel('Title or MAL ID').fill('no such title');
  await page.getByRole('button', { name: 'Apply filters' }).click();
  await expect(page.getByRole('heading', { name: 'No anime match these filters' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Export matching CSV' })).toBeDisabled();
});

test('a new private workspace can import a file and recover from a rejected one', async ({ page }) => {
  let imported = false;
  await page.route('**/api/anime?*', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify(imported ? animeFixture : { snapshot: null }) }));
  await page.route('**/api/anime/import?*', async route => { imported = true; await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ...animeFixture, created: true, message: 'Anime export imported privately.' }) }); });
  await page.goto('/anime');
  await expect(page.getByRole('heading', { name: 'Bring your anime list into focus' }).first()).toBeVisible();
  await page.getByLabel('MAL export file').setInputFiles({ name: 'wrong.txt', mimeType: 'text/plain', buffer: Buffer.from('wrong') });
  await expect(page.getByRole('alert').filter({ hasText: 'Choose a non-empty MAL' })).toBeVisible();
  await page.getByLabel('MAL export file').setInputFiles({ name: 'anime.xml.gz', mimeType: 'application/gzip', buffer: Buffer.from('synthetic upload; parser tested on backend') });
  await expect(page.getByRole('status').filter({ hasText: 'Anime export imported privately.' })).toBeVisible();
  await expect(page.getByText('anime_fixture · 65 titles')).toBeVisible();
  await page.route('**/api/anime/import?*', route => route.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ detail: 'Header title count does not match the export; nothing was imported.' }) }));
  await page.getByLabel('MAL export file').setInputFiles({ name: 'bad.xml', mimeType: 'application/xml', buffer: Buffer.from('<bad/>') });
  await expect(page.getByRole('alert').filter({ hasText: 'nothing was imported' })).toBeVisible();
  await expect(page.getByText('anime_fixture · 65 titles')).toBeVisible();
});

test('API failures have an honest retry and invalid snapshots do not reveal other accounts', async ({ page }) => {
  await page.route('**/api/anime*', route => route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: 'No such snapshot in your Anime workspace.' }) }));
  await page.goto('/anime?anime_snapshot=987');
  await expect(page.getByText('No such snapshot in your Anime workspace.', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('anime_fixture · 65 titles')).toHaveCount(0);
  await page.unroute('**/api/anime*');
  await page.getByRole('button', { name: 'TRY AGAIN' }).first().click();
  await expect(page.getByText('anime_fixture · 65 titles')).toBeVisible();
});

test('responsive library confines overflow to its keyboard-accessible table', async ({ page }) => {
  await page.goto('/anime?tab=library&anime_page=999999');
  await expect(page.getByText('51–65 of 65 titles', { exact: true })).toBeVisible();
  const region = page.getByRole('region', { name: 'Anime results table' });
  await expect(region).toHaveAttribute('tabindex', '0');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await expect(page.getByRole('tab', { name: /MY LIBRARY/ })).toHaveAttribute('aria-selected', 'true');
  await page.getByText('Import history & source fingerprint').click();
  await expect(page.getByRole('link', { name: /65 titles · viewing/ })).toBeVisible();
});

test('taste metadata drills into the exact watched subset and preserves filters', async ({ page }) => {
  await page.goto('/anime?tab=taste');
  await expect(page.getByText('Metadata: 64 / 65 titles', { exact: false })).toBeVisible();
  await expect(page.getByRole('region', { name: 'YOUR SCORES VS THE COMMUNITY' })).toContainText('not MAL community scores');
  await expect(page.getByRole('region', { name: 'WATCH TIME, WITH THE LIMITS VISIBLE' })).toContainText('228');
  await page.getByLabel('Minimum titles per trait').selectOption('10');
  await page.reload();
  await expect(page.getByLabel('Minimum titles per trait')).toHaveValue('10');
  await page.getByRole('region', { name: 'THE GENRES YOU GRAVITATE TO' }).getByRole('link', { name: 'Action', exact: true }).click();
  await expect(page.getByLabel('Genre', { exact: true })).toHaveValue('Action');
  await expect(page.getByLabel('List scope')).toHaveValue('watched');
  await expect(page.getByText('1–28 of 28 titles', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText('1–28 of 28 titles', { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
});

test('backlog picks explain evidence, respect time filters and recover from no matches', async ({ page }) => {
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto('/anime?tab=discover');
  const panel = page.getByRole('region', { name: 'WHAT TO WATCH FROM YOUR BACKLOG' });
  await expect(panel).toContainText('25 scored examples');
  await expect(panel).toContainText('first 9 of 9 matches');
  await page.getByLabel('Estimated total time').selectOption('180');
  await page.getByRole('button', { name: 'Update picks' }).click();
  await expect(page.getByRole('heading', { name: 'No supported picks match yet' })).toBeVisible();
  await page.reload();
  await expect(page.getByLabel('Estimated total time')).toHaveValue('180');
  await page.getByRole('button', { name: 'Reset picks' }).click();
  await expect(panel).toContainText('first 9 of 9 matches');
  await expect(page.getByLabel('Estimated total time')).toHaveValue('');
  await panel.getByRole('link', { name: 'Inspect your list entry →' }).first().click();
  await expect(page).toHaveURL(/tab=library&anime_id=56/);
  await expect(page.getByText('1–1 of 1 titles', { exact: true })).toBeVisible();
  await expect(page.getByText('Exact title: MAL 56.', { exact: false })).toBeVisible();
  expect(errors).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
});
