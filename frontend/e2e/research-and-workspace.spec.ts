import { expect, test } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import { installApiMocks } from './fixtures/api';

const RESEARCH = '/films?tab=research&profiles=alpha&profiles=bravo&research_from=2026-07-01&research_to=2026-07-31';
const STORAGE_KEY = 'spyboxd.workspace.v1:user_e2e';
test.beforeEach(async ({ page }) => { await installApiMocks(page); });

test('research filters and second group reach the API, with uncertainty and reload persistence', async ({ page }) => {
  await page.goto(RESEARCH);
  await expect(page.getByRole('heading', { name: /COMPARE PERIODS AND GROUPS/ })).toBeVisible();
  const activeTab = page.getByRole('tab', { name: 'RESEARCH4', exact: true });
  await expect(activeTab).toBeInViewport();
  await expect(page.getByText('5 known watches have no diary date', { exact: false })).toBeVisible();
  await page.getByText('Compare a second group · 0 selected', { exact: true }).click();
  await page.getByLabel('Compare @bravo', { exact: true }).check();
  await expect(page.getByRole('heading', { name: 'Group B · 1 members' })).toBeVisible();
  await expect(page.getByText('Groups share members; their observations', { exact: false })).toBeVisible();
  await page.getByLabel('Research date basis').selectOption('logged');
  await page.getByLabel('Order research evidence').selectOption('title');
  await page.getByLabel('Search research evidence').fill('Evidence Film 02');
  const request = page.waitForRequest((req) => req.url().includes('/api/research') && req.url().includes('q=Evidence'));
  await page.getByRole('button', { name: 'Apply research filters' }).click();
  const params = new URL((await request).url()).searchParams;
  expect(params.getAll('profiles')).toEqual(['alpha', 'bravo']);
  expect(params.getAll('compare_profiles')).toEqual(['bravo']);
  expect(params.get('basis')).toBe('logged');
  expect(params.get('sort')).toBe('title');
  await expect(page.getByRole('button', { name: 'Export all 1 matching watches (CSV)' })).toBeVisible();
  await page.reload();
  await expect(page.getByLabel('Search research evidence')).toHaveValue('Evidence Film 02');
  await expect(page.getByLabel('Research date basis')).toHaveValue('logged');
  await page.getByRole('button', { name: 'Inspect Drama in group A' }).click();
  await expect(page).toHaveURL(/research_trait=Drama/);
  await page.getByRole('button', { name: 'Clear trait filter' }).click();
  await expect(page).not.toHaveURL(/research_trait=/);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  expect(await page.getByRole('region', { name: 'COMPARE PERIODS AND GROUPS', exact: true }).locator('p').evaluateAll((paragraphs) => paragraphs.every((paragraph) => paragraph.scrollWidth <= paragraph.clientWidth + 1))).toBe(true);
  expect(await page.getByRole('region', { name: 'COMPARE PERIODS AND GROUPS', exact: true }).locator('.overflow-x-auto').evaluateAll((tables) => tables.every((table) => table.scrollWidth <= table.clientWidth + 1))).toBe(true);
});

test('CSV contains all pages exactly once and neutralizes spreadsheet formulas', async ({ page }) => {
  await page.goto(RESEARCH);
  await expect(page.getByText('1–50 of 60 events', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Next evidence page' }).click();
  await expect(page.getByText('51–60 of 60 events', { exact: true })).toBeVisible();
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export all 60 matching watches (CSV)' }).click();
  const file = await (await download).path();
  const csv = await readFile(file!, 'utf8');
  const lines = csv.trimEnd().split('\r\n');
  expect(lines).toHaveLength(61);
  expect(new Set(lines.slice(1).map((line) => line.split(',')[0])).size).toBe(60);
  expect(csv).toContain('"\'=Fixture formula"');
  expect(csv).toContain('"source_kind"');
  await expect(page.getByText('Exported 60 matching watch events.', { exact: false })).toBeVisible();
});

test('empty and failed research never claim profiles were inactive', async ({ page }) => {
  await page.goto(RESEARCH + '&research_q=no-such-film');
  await expect(page.getByText('No diary events match these filters.', { exact: false })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Export all 0 matching watches (CSV)' })).toBeDisabled();
  await page.route('**/api/research?**', (route) => route.fulfill({ status: 422, contentType: 'application/json', body: JSON.stringify({ detail: 'Choose an ordered date range.' }) }));
  await page.reload();
  await expect(page.getByText('Choose an ordered date range.', { exact: false }).first()).toBeVisible();
  await expect(page.getByText('No diary events match these filters.', { exact: false })).toHaveCount(0);
});

test('saved groups load without discarding filters, persist and can be removed', async ({ page }) => {
  await page.goto(RESEARCH + '&research_page=1');
  await page.getByText('Saved groups · 0', { exact: true }).click();
  await page.getByLabel('Saved group name').fill('Friday crew');
  await page.getByRole('button', { name: 'Save selected group' }).click();
  await expect(page.getByText('Saved “Friday crew” in this browser', { exact: false })).toBeVisible();
  await page.getByRole('link', { name: '@charlie', exact: true }).click();
  await expect(page).toHaveURL(/profiles=charlie/);
  await page.getByRole('link', { name: 'Friday crew · 2', exact: true }).click();
  await expect(page).not.toHaveURL(/profiles=charlie/);
  expect(new URL(page.url()).searchParams.getAll('profiles')).toEqual(['alpha', 'bravo']);
  expect(new URL(page.url()).searchParams.get('research_from')).toBe('2026-07-01');
  expect(new URL(page.url()).searchParams.has('research_page')).toBe(false);
  await page.reload();
  await page.getByText('Your workspace · 1 groups · 0 pinned stats', { exact: true }).click();
  await page.getByRole('button', { name: 'Remove saved group Friday crew' }).click();
  await expect(page.getByText('Your workspace · 0 groups · 0 pinned stats', { exact: true })).toBeVisible();
});

test('pins and custom overview survive reload, hidden panels stay out of the outline', async ({ page }) => {
  await page.goto('/overview?profiles=alpha&profiles=bravo');
  await page.getByRole('button', { name: 'Pin MARATHON DAYS', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Unpin MARATHON DAYS', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await page.getByText('Customise your overview', { exact: true }).click();
  await page.getByLabel('Show MARATHON DAYS', { exact: true }).uncheck();
  await expect(page.locator('.terminal-root section')).toHaveCount(7);
  await page.reload();
  await expect(page.locator('.terminal-root section')).toHaveCount(7);
  await page.getByText('Jump to a statistic · 7 panels', { exact: true }).click();
  await expect(page.getByRole('navigation', { name: 'Statistics on this page' }).getByRole('link', { name: 'MARATHON DAYS', exact: true })).toHaveCount(0);
  await page.getByText('Customise your overview', { exact: true }).click();
  await page.getByRole('button', { name: 'Restore all overview panels' }).click();
  await expect(page.locator('.terminal-root section')).toHaveCount(8);
  await page.getByText('Your workspace · 0 groups · 1 pinned stats', { exact: true }).click();
  await page.getByRole('link', { name: 'MARATHON DAYS', exact: true }).first().click();
  await expect(page).toHaveURL(/profiles=alpha.*#insight-marathon-days-/);
  await expect(page.getByRole('heading', { name: /MARATHON DAYS/ })).toBeInViewport();
});

test('malformed or another account’s preferences cannot leak into this workspace', async ({ page }) => {
  await page.addInitScript(({ key }) => {
    localStorage.setItem(key, '{bad JSON');
    localStorage.setItem('spyboxd.workspace.v1:someone_else', JSON.stringify({ version: 1, groups: [{ id: 'private', name: 'Not this user', profiles: ['alpha'] }] }));
  }, { key: STORAGE_KEY });
  await page.goto('/overview');
  await expect(page.locator('.terminal-root section')).toHaveCount(8);
  await expect(page.getByText('Your workspace · 0 groups · 0 pinned stats', { exact: true })).toBeVisible();
  await expect(page.getByText('Not this user')).toHaveCount(0);
});

test('a statistic pinned from a default subject stores the actual profile', async ({ page }) => {
  await page.goto('/people?tab=one');
  await page.getByRole('button', { name: 'Pin WHAT LANGUAGE THE FILMS SPEAK', exact: true }).click();
  await page.getByText('Your workspace · 0 groups · 1 pinned stats', { exact: true }).click();
  const pin = page.getByRole('link', { name: 'WHAT LANGUAGE THE FILMS SPEAK · @alpha', exact: true });
  await expect(pin).toHaveAttribute('href', /subject=alpha#insight-/);
});

test('denied browser storage leaves the app usable and reports unsaved preferences', async ({ page }) => {
  await page.addInitScript(() => { Object.defineProperty(Storage.prototype, 'setItem', { value() { throw new DOMException('Blocked', 'SecurityError'); } }); });
  await page.goto('/overview');
  await page.getByRole('button', { name: 'Pin MARATHON DAYS', exact: true }).click();
  await expect(page.getByText('Storage unavailable', { exact: true })).toBeVisible();
  await expect(page.locator('.terminal-root section')).toHaveCount(8);
  await expect(page.getByRole('button', { name: 'Pin MARATHON DAYS', exact: true })).toHaveAttribute('aria-pressed', 'false');
});

test('recommendation evaluation is lazy, shows the baseline and limits its claims', async ({ page }) => {
  const requests: string[] = [];
  page.on('request', (request) => { if (request.url().includes('/api/recommendation-evaluation')) requests.push(request.url()); });
  await page.goto('/tonight?profiles=alpha&profiles=bravo');
  const trigger = page.getByText('Test the rating component against held-out ratings', { exact: true });
  await expect(trigger).toBeVisible();
  expect(requests).toHaveLength(0);
  await trigger.click();
  await expect(page.getByText('Mean-rating-only baseline: 3.90★.', { exact: false })).toBeVisible();
  await expect(page.getByText('Not a temporal backtest', { exact: false })).toBeVisible();
  expect(requests).toHaveLength(1);
  await page.getByText('Inspect the films used in this test', { exact: true }).click();
  await expect(page.getByText('Held Out Fixture Film (4.00★)', { exact: false }).first()).toBeVisible();
});
