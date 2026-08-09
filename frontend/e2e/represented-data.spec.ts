import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * Ten data points were collected or computed, served by the API, and rendered
 * nowhere — mostly a key inside a payload whose siblings a panel already drew.
 * The backend had done the work every time; only the last mile was missing.
 * Each one is pinned here, because "nobody rendered it" is exactly the kind of
 * regression no other test notices.
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

test("Letterboxd's own stats page is shown, labelled, and attributed to them", async ({ page }) => {
  await page.goto('/people?tab=one&subject=alpha');

  const panel = page
    .locator('.terminal-root section', { hasText: 'WHAT LETTERBOXD SAYS ABOUT THEM' })
    .first();
  await expect(panel).toBeVisible();
  // Renamed for a reader, not dumped as the raw key.
  await expect(panel.getByText('Hours watched', { exact: true })).toBeVisible();
  await expect(panel.getByText('2,130')).toBeVisible();
  await expect(panel.getByText('Longest streak', { exact: true })).toBeVisible();
  // Their figures, and the panel says whose they are.
  await expect(panel).toContainText('Their figures, not ours');
});

test('a key Letterboxd sends that we did not anticipate is still rendered', async ({ page }) => {
  await page.goto('/people?tab=one&subject=alpha');

  const panel = page
    .locator('.terminal-root section', { hasText: 'WHAT LETTERBOXD SAYS ABOUT THEM' })
    .first();
  // `highest_rated_year` has no entry in the label map; it must appear with
  // its underscores stripped rather than be dropped.
  await expect(panel.getByText('highest rated year', { exact: true })).toBeVisible();
  await expect(panel.getByText('2,018')).toBeVisible();
});

test('return journeys report the second viewing, not just the rewatch', async ({ page }) => {
  await page.goto('/people?tab=one&subject=alpha');

  const panel = page.locator('.terminal-root section', { hasText: 'WHEN THEY WENT BACK' }).first();
  await expect(panel).toBeVisible();
  await expect(panel.getByText('MEDIAN DAYS BETWEEN')).toBeVisible();
  await expect(panel.getByText('AVG RATING CHANGE')).toBeVisible();
  await expect(panel.getByText('Rated it higher')).toBeVisible();
  await expect(panel.getByText('Rated it lower')).toBeVisible();
  await expect(panel.getByText('Landed on the same star')).toBeVisible();
});

test('the director gender split names its denominator rather than the library', async ({ page }) => {
  await page.goto('/people?tab=one&subject=alpha');

  const panel = page
    .locator('.terminal-root section', { hasText: 'WHO DIRECTED WHAT THEY WATCH' })
    .first();
  await expect(panel).toBeVisible();
  await expect(panel.getByText('Directed by women', { exact: true })).toBeVisible();
  await expect(panel.getByText('Mixed directing teams', { exact: true })).toBeVisible();
  // A film with no recorded gender is excluded, and the caveat says so — the
  // three counts deliberately do not add up to the library.
  await expect(panel).toContainText('940');
  await expect(panel).toContainText('left out of the share');
});

test('their highest-rated corners are shown with the average\'s own denominator', async ({ page }) => {
  await page.goto('/people?tab=one&subject=alpha');

  const panel = page.locator('.terminal-root section', { hasText: 'WHERE THEY RATE HIGHEST' }).first();
  await expect(panel).toBeVisible();
  await expect(panel.getByText('Genre', { exact: true })).toBeVisible();
  await expect(panel.getByText('Decade', { exact: true })).toBeVisible();
  await expect(panel.getByText('Director', { exact: true })).toBeVisible();
  // RATED is the denominator, distinct from the bucket size.
  await expect(panel.getByText('RATED', { exact: true })).toBeVisible();
});

test('the executive producer joins the crew rollup it was computed beside', async ({ page }) => {
  await page.goto('/people?tab=one&subject=alpha');

  const panel = page
    .locator('.terminal-root section', { hasText: 'THE CREW BEYOND THE BIG THREE' })
    .first();
  await expect(panel.getByText('Executive producer', { exact: true })).toBeVisible();
  await expect(panel.getByText('Stan Lee')).toBeVisible();
});

test('a year in the taste timeline reports its rewatches and likes', async ({ page }) => {
  await page.goto('/people?tab=one&subject=alpha');

  const panel = page.locator('.terminal-root section', { hasText: 'GETTING HARSHER OR SOFTER' }).first();
  await expect(panel).toBeVisible();
  // The hint carries the year's shape, not only its average.
  await expect(panel.locator('[title*="rewatches"]').first()).toBeVisible();
});

test('the member card shows the links the profile supplied', async ({ page }) => {
  await page.goto('/people?tab=reach&subject=alpha');

  const panel = page.locator('.terminal-root section', { hasText: 'MEMBER CARD' }).first();
  await expect(panel).toBeVisible();
  await expect(panel.getByText('Links', { exact: true })).toBeVisible();
  await expect(panel).toContainText('letterboxd.com/alpha');
});

test('liked writing is counted by author, and unresolved likes are declared', async ({ page }) => {
  await page.goto('/people?tab=reach&subject=alpha');

  const panel = page.locator('.terminal-root section', { hasText: 'WHOSE WRITING THEY LIKE' }).first();
  await expect(panel).toBeVisible();
  await expect(panel.getByText('@carol')).toBeVisible();
  // Excluded rather than pooled under "unknown", and the panel says how many.
  await expect(panel).toContainText('1 like');
  await expect(panel).toContainText('could not be traced');
});

test('lost history shows the text, and says so when an entry never had any', async ({ page }) => {
  await page.goto('/people?tab=reach&subject=alpha');

  const panel = page
    .locator('.terminal-root section', { hasText: 'WHAT LETTERBOXD NO LONGER HAS' })
    .first();
  await expect(panel).toBeVisible();
  await expect(panel.getByText('A Film Letterboxd Forgot (1998)')).toBeVisible();
  await expect(panel).toContainText('The projector broke twice');
  // An entry with no body is stated as such rather than left blank, which
  // would read as text we failed to keep.
  await expect(panel.getByText('no text in the entry')).toBeVisible();
});

test('a ranked list is distinguishable from a bag of films', async ({ page }) => {
  await page.goto('/tonight?tab=lists');

  const panel = page.locator('.terminal-root section', { hasText: 'WORK THROUGH A LIST' }).first();
  await expect(panel.getByText('ORDER', { exact: true })).toBeVisible();
  await expect(panel.getByText('ranked', { exact: true })).toBeVisible();
  await expect(panel.getByText('unordered', { exact: true })).toBeVisible();
});
