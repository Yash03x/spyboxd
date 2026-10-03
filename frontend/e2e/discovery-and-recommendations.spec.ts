import { expect, test } from '@playwright/test';
import { installApiMocks } from './fixtures/api';

test.beforeEach(async ({ page }) => { await installApiMocks(page); });

test('recommendation filters reach the API, survive reload and clear without changing the group', async ({ page }) => {
  await page.goto('/tonight?tab=picks&profiles=alpha&profiles=bravo&region=DE');
  await page.getByLabel('Maximum runtime', { exact: true }).selectOption('120');
  await page.getByLabel('Genre', { exact: true }).selectOption('Drama');
  await page.getByLabel('Rewatches', { exact: true }).selectOption('unseen');
  const request = page.waitForRequest((req) => req.url().includes('/api/watch-together') && req.url().includes('availability=flatrate'));
  await page.getByLabel('Watch options', { exact: true }).selectOption('flatrate');
  const api = new URL((await request).url());
  expect(api.searchParams.get('max_runtime')).toBe('120');
  expect(api.searchParams.get('genre')).toBe('Drama');
  expect(api.searchParams.get('rewatch')).toBe('unseen');
  expect(api.searchParams.getAll('profiles')).toEqual(['alpha', 'bravo']);
  await page.reload();
  await expect(page.getByLabel('Maximum runtime', { exact: true })).toHaveValue('120');
  await expect(page.getByLabel('Rewatches', { exact: true })).toHaveValue('unseen');
  await page.getByRole('link', { name: 'Clear filters', exact: true }).click();
  expect(new URL(page.url()).searchParams.getAll('profiles')).toEqual(['alpha', 'bravo']);
  await expect(page.getByLabel('Availability country')).toHaveValue('DE');
  await expect(page.getByLabel('Maximum runtime', { exact: true })).toHaveValue('');
});

test('insight search finds group trends and preserves the chosen group', async ({ page }) => {
  await page.goto('/overview?profiles=alpha&profiles=bravo');
  await page.getByText('Find a stat, profile or group trend', { exact: true }).click();
  await page.getByLabel('What would you like to explore?').fill('group trends');
  await page.getByRole('navigation', { name: 'Insight guide' }).getByRole('link', { name: /Explore group trends and taste/ }).click();
  await expect(page).toHaveURL(/tab=trends/);
  expect(new URL(page.url()).searchParams.getAll('profiles')).toEqual(['alpha', 'bravo']);
  await expect(page.getByRole('heading', { name: /THE GROUP OVER TIME/ })).toBeVisible();
  await page.getByLabel('Taste dimension').selectOption('director');
  await expect(page).toHaveURL(/trait=director/);
  await expect(page.getByLabel('Order traits')).toHaveValue('watched');
  await page.getByLabel('Order traits').selectOption('alignment');
  await expect(page).toHaveURL(/trait_order=alignment/);
  await page.goBack();
  await expect(page.getByLabel('Order traits')).toHaveValue('watched');
  await expect(page.getByLabel('Taste dimension')).toHaveValue('director');
});

test('availability country updates results and supports browser history', async ({ page }) => {
  await page.goto('/tonight?tab=leaving&region=ALL&profiles=alpha&profiles=bravo');
  const request = page.waitForRequest((req) => req.url().includes('/api/tonight/availability') && new URL(req.url()).searchParams.get('region') === 'DE');
  await page.getByLabel('Availability country', { exact: true }).selectOption('DE');
  await request;
  await expect(page.getByLabel('Availability country', { exact: true })).toHaveValue('DE');
  expect(new URL(page.url()).searchParams.getAll('profiles')).toEqual(['alpha', 'bravo']);
  await page.goBack();
  await expect(page.getByLabel('Availability country', { exact: true })).toHaveValue('ALL');
  await page.goForward();
  await expect(page.getByLabel('Availability country', { exact: true })).toHaveValue('DE');
});

test('profile search changes the visible choices, not the selected group', async ({ page }) => {
  await page.goto('/films?tab=trends&profiles=alpha&profiles=bravo');
  const search = page.getByLabel('Find a profile to select');
  await search.fill('@delta');
  await expect(page.getByRole('status').filter({ hasText: '1 matching profiles' })).toBeVisible();
  expect(new URL(page.url()).searchParams.getAll('profiles')).toEqual(['alpha', 'bravo']);
  await page.getByRole('link', { name: '@delta', exact: true }).click();
  await expect(page).toHaveURL(/profiles=delta/);
  expect(new URL(page.url()).searchParams.getAll('profiles')).toEqual(['alpha', 'bravo', 'delta']);
  await search.fill('');
  await expect(page.getByRole('link', { name: '@alpha', exact: true })).toBeVisible();
});

test('the long individual page has a searchable outline of its actual panels', async ({ page }) => {
  await page.goto('/people?tab=one&subject=alpha');
  await page.getByText('Jump to a statistic · 33 panels', { exact: true }).click();
  await page.getByLabel('Find a statistic on this page').fill('language');
  await page.getByRole('navigation', { name: 'Statistics on this page' }).getByRole('link', { name: 'WHAT LANGUAGE THE FILMS SPEAK' }).click();
  await expect(page).toHaveURL(/#insight-/);
  await expect(page.getByRole('heading', { name: /WHAT LANGUAGE THE FILMS SPEAK/ })).toBeInViewport();
  const anchor = new URL(page.url()).hash;
  await page.reload();
  await expect(page.locator(anchor)).toBeAttached();
  await expect(page.getByRole('heading', { name: /WHAT LANGUAGE THE FILMS SPEAK/ })).toBeInViewport();
});

test('navigation has visible labels and remains within the viewport', async ({ page }) => {
  await page.goto('/tonight');
  const navigation = page.getByRole('navigation', { name: 'Sections', exact: true });
  for (const name of ['Overview', 'Overlaps', 'People', 'Tonight', 'Films', 'Data']) {
    await expect(navigation.getByText(name, { exact: true })).toBeVisible();
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
});
