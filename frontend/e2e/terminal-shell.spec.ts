import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * The redesign's shell and the two sections that have moved onto it.
 *
 * These assertions are deliberately about *copy* as much as structure: the
 * rename from schema language to plain English is the largest single change in
 * the redesign, and a panel that silently reverts to "gap days" or "signal" is
 * a regression nothing else would catch.
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page, { isAdmin: true });
});

test('the old dashboard path redirects to Overview', async ({ page }) => {
  await page.goto('/dashboard');
  await expect(page).toHaveURL(/\/overview$/);
});

test('the old spy-signals path redirects to Overlaps', async ({ page }) => {
  await page.goto('/spy-signals');
  await expect(page).toHaveURL(/\/overlaps$/);
});

test('Overview renders the eight panels, each naming the table it reads', async ({ page }) => {
  await page.goto('/overview');

  for (const title of [
    'THE GROUP, IN FIVE NUMBERS',
    'THE LATEST CHANGES WE DETECTED',
    'WHO WATCHES WITH WHOM',
    'EVERYONE WE ARE WATCHING',
    'THIS YEAR, MONTH BY MONTH',
    'HOW THE GROUP RATES',
    'MARATHON DAYS',
    'LEAVING SOON',
  ]) {
    await expect(page.getByText(`▸ ${title}`, { exact: false }).first()).toBeVisible();
  }

  // Every panel header carries the table it reads, so no figure on the page is
  // a claim without a source.
  await expect(page.getByText('watch_events.watched_date').first()).toBeVisible();
});

test('the status bar names the section and the rail marks it active', async ({ page }) => {
  await page.goto('/overview');

  await expect(page.getByText('01 OVERVIEW')).toBeVisible();
  await expect(page.getByRole('link', { name: '01 Overview' })).toHaveAttribute(
    'aria-current',
    'page',
  );
});

test('a profile with no join date shows when it started logging, never a guess', async ({ page }) => {
  await page.goto('/overview');

  // Letterboxd publishes no join date on a public page. The column is the
  // earliest diary entry we hold, and the caveat says so rather than letting
  // the reader assume it is a join date.
  await expect(page.getByText('SINCE', { exact: true }).first()).toBeVisible();
  await expect(
    page.getByText('SINCE is the earliest diary entry we hold, not a join date', {
      exact: false,
    }),
  ).toBeVisible();
});

test('what-changed rows link to the section that explains them', async ({ page }) => {
  await page.goto('/overview');

  const row = page.getByRole('link', { name: /Fixture Film reviewed/ });
  await expect(row).toBeVisible();
  await row.click();

  // A change is a pointer into the product, not a dead end. Reach is still on
  // its legacy path, so the link resolves there rather than to a 404.
  await expect(page).toHaveURL(/\/(people|analysis)/);
});

test('leaving soon refuses to invent a countdown it cannot read', async ({ page }) => {
  await page.goto('/overview');

  await expect(page.getByText('Can’t answer this yet')).toBeVisible();
  await expect(
    page.getByText('The provider feed publishes which services carry a film today', {
      exact: false,
    }),
  ).toBeVisible();
});

test('the closeness control says "same day", not "gap days"', async ({ page }) => {
  await page.goto('/overlaps');

  await expect(page.getByRole('link', { name: 'SAME DAY' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'WITHIN A DAY' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'WITHIN THREE' })).toBeVisible();

  // No control may be labelled in the old schema language. The caveat below
  // the panel still names what the words replaced — that is the rename being
  // explained, not the rename leaking.
  await expect(page.getByRole('link', { name: /gap days/i })).toHaveCount(0);
  await expect(page.getByRole('link', { name: /Spy Signals/i })).toHaveCount(0);
});

test('the tab lives in the URL so it survives a reload', async ({ page }) => {
  await page.goto('/overlaps');
  await page.getByRole('tab', { name: /WHEN/ }).click();

  await expect(page).toHaveURL(/tab=when/);
  await page.reload();
  await expect(page.getByText('▸ WEEKDAY RHYTHM', { exact: false })).toBeVisible();
});

test('every Overlaps tab renders its own panels', async ({ page }) => {
  await page.goto('/overlaps?tab=together');
  await expect(page.getByText('▸ WHAT OVERLAPPED', { exact: false })).toBeVisible();
  await expect(page.getByText('▸ PAIR LEADERBOARD', { exact: false })).toBeVisible();

  await page.goto('/overlaps?tab=echoes');
  await expect(page.getByText('▸ WATCHED IT AGAIN, SO DID THEY', { exact: false })).toBeVisible();
  await expect(page.getByText('▸ SHARED FIRSTS', { exact: false })).toBeVisible();

  await page.goto('/overlaps?tab=when');
  await expect(page.getByText('▸ SEASON SHAPE', { exact: false })).toBeVisible();

  await page.goto('/overlaps?tab=sure');
  await expect(page.getByText('▸ HOW SURE WE ARE', { exact: false })).toBeVisible();
  await expect(page.getByText('▸ LOGGING LAG', { exact: false })).toBeVisible();
});

test('a new signal is marked as new and an existing one is not', async ({ page }) => {
  await page.goto('/overlaps?tab=echoes');

  const sharedFirsts = page.locator('section', { hasText: 'SHARED FIRSTS' }).first();
  await expect(sharedFirsts.getByText('NEW', { exact: true })).toBeVisible();

  const echoes = page.locator('section', { hasText: 'WATCHED IT AGAIN' }).first();
  await expect(echoes.getByText('NEW', { exact: true })).toHaveCount(0);
});

test('the first visit follows the OS, and a choice then outranks it', async ({ page }) => {
  // prefers-color-scheme decides the first visit only. Emulating dark here
  // makes that contract the thing under test rather than the runner's default.
  await page.emulateMedia({ colorScheme: 'dark' });
  await page.goto('/overview');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');

  await page.getByRole('button', { name: /LIGHT/ }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');

  // The OS still says dark. The stored choice has to win, and it has to win
  // before first paint rather than after a flash.
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
});

test('no wrapper in the shell can hide the page behind an animation', async ({ page }) => {
  await page.goto('/overview');

  // A frozen animation clock in a background tab once left the app rendering
  // at 1.8% opacity. Nothing in the terminal shell may animate its own opacity
  // from zero, so the panel grid is opaque on arrival.
  const opacity = await page.locator('.terminal-root').evaluate(
    (node) => Number(getComputedStyle(node).opacity),
  );
  expect(opacity).toBe(1);
});
