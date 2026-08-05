import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * The last three sections: Films, Tonight and Data.
 *
 * As with the rest of the redesign, most of what is pinned here is *honesty* —
 * a ratio that has no denominator is blank rather than zero, a surface that was
 * never read is distinguishable from one that came back empty, and the panel
 * the section was designed around says why it cannot exist.
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page, { isAdmin: true });
});

test('the rail reaches all six sections', async ({ page }) => {
  await page.goto('/overview');

  for (const [ordinal, name, path] of [
    ['01', 'Overview', '/overview'],
    ['02', 'Overlaps', '/overlaps'],
    ['03', 'People', '/people'],
    ['04', 'Tonight', '/tonight'],
    ['05', 'Films', '/films'],
    ['06', 'Data', '/data'],
  ] as const) {
    const link = page.getByRole('link', { name: `${ordinal} ${name}` });
    await expect(link).toHaveAttribute('href', path);
  }
});

test('watch-together redirects into Tonight', async ({ page }) => {
  await page.goto('/watch-together');
  await expect(page).toHaveURL(/\/tonight$/);
});

test('Films states the match rate as the ceiling on its own panels', async ({ page }) => {
  await page.goto('/films?tab=library');

  const keywords = page.locator('.terminal-root section', { hasText: 'SUBJECTS THEY RETURN TO' }).first();
  await expect(keywords).toContainText('grief');
  // Every panel here reads the enrichment cache, so every panel here publishes
  // the share of the library that cache actually covers.
  await expect(keywords).toContainText('3,643 of 4,187 distinct films');
});

test('a runtime band nobody queued has no ratio rather than a ratio of zero', async ({ page }) => {
  await page.goto('/films?tab=library');

  const panel = page.locator('.terminal-root section', { hasText: 'RUNTIME APPETITE' }).first();
  const row = panel.locator('div').filter({ hasText: 'over 150' }).last();
  await expect(row).toContainText('—');
  await expect(row).not.toContainText('0.00×');
});

test('an unrated series shows no average rather than zero', async ({ page }) => {
  await page.goto('/films?tab=library');

  const panel = page.locator('.terminal-root section', { hasText: 'SERIES WORKED THROUGH' }).first();
  const row = panel.locator('div').filter({ hasText: 'Apu trilogy' }).last();
  await expect(row).toContainText('—');
  await expect(row).not.toContainText('0.0');
});

test('the Gaps tab ranks unenriched films by how often they appear', async ({ page }) => {
  await page.goto('/films?tab=gaps');

  await expect(page.getByText('▸ MISSING METADATA, RANKED BY EXPOSURE', { exact: false })).toBeVisible();
  const panel = page.locator('.terminal-root section', { hasText: 'MATCH RATE' }).first();
  await expect(panel).toContainText('87%');
  await expect(panel).toContainText('No confident title and year match');
});

test('Tonight ranks a shortlist and explains the top row', async ({ page }) => {
  await page.goto('/tonight?tab=picks');

  await expect(page.getByText("▸ TONIGHT'S SHORTLIST", { exact: false })).toBeVisible();
  const why = page.locator('.terminal-root section').filter({ hasText: /▸ WHY .+ FITS/ }).first();
  await expect(why).toBeVisible();
  // Fit is a rank across the room, and the panel says so rather than letting
  // the number read as a rating.
  await expect(why).toContainText('rank across the selected room, not a rating');
});

test('Tonight refuses to invent a leaving countdown', async ({ page }) => {
  await page.goto('/tonight?tab=leaving');

  const panel = page.locator('.terminal-root section', { hasText: 'WHY THERE IS NO COUNTDOWN' }).first();
  await expect(panel.getByRole('heading', { name: 'Can’t answer this yet' })).toBeVisible();
  await expect(panel).toContainText('a guess wearing a number’s clothes');

  // A stale region is greyed and labelled, never hidden.
  const freshness = page.locator('.terminal-root section', { hasText: 'HOW FRESH THIS IS' }).first();
  await expect(freshness).toContainText('Stale — shown greyed, not hidden');
});

test('Tonight reconciles the list counts its own panels disagreed about', async ({ page }) => {
  await page.goto('/tonight?tab=lists');

  // On production this tab reported 1, 49 and 17 for the same word: one panel
  // read only public lists, one read every list in the store including other
  // people's, and one counted the owner's private export lists flat. The
  // cadence table now shows both numbers so the smaller ones read as a scope
  // rather than a fault.
  const cadence = page.locator('.terminal-root section', { hasText: 'WHO KEEPS THEIR LISTS ALIVE' }).first();
  await expect(cadence).toContainText('SHOWN');
  await expect(cadence).toContainText('appear in no other panel on this tab');
});

test('Data separates a surface never read from one that came back empty', async ({ page }) => {
  await page.goto('/data?tab=refreshes');

  const ledger = page.locator('.terminal-root section', { hasText: 'PER-SURFACE REFRESH LEDGER' }).first();
  await expect(ledger).toContainText('Never read for any selected profile');
  await expect(ledger).toContainText(
    'which is different from being read and coming back empty',
  );
});

test('a backing-off feed publishes the wait rather than a spinner', async ({ page }) => {
  await page.goto('/data?tab=refreshes');

  const feeds = page.locator('.terminal-root section', { hasText: 'FEED HEALTH AND BACKOFF' }).first();
  await expect(feeds).toContainText('backing off after HTTP 429');
});

test('an unread profile total is "not read", never zero', async ({ page }) => {
  await page.goto('/data?tab=missing');

  const counts = page.locator('.terminal-root section', { hasText: 'THEIR NUMBERS AGAINST OURS' }).first();
  await expect(counts).toContainText('not read');
  await expect(counts).toContainText('is not a gap of zero');
});

test('feature readiness names the panel, not the schema', async ({ page }) => {
  await page.goto('/data?tab=missing');

  const readiness = page.locator('.terminal-root section', { hasText: 'WHAT EACH VIEW IS WAITING FOR' }).first();
  await expect(readiness).toBeVisible();
  // Renamed from "spy_signals" and friends: the schema is allowed in the SRC
  // line and nowhere else.
  await expect(readiness).not.toContainText('spy_signals');
  await expect(readiness).not.toContainText('taste_dna');
});

test('Lost & found explains why deleted history exists at all', async ({ page }) => {
  await page.goto('/data?tab=lost');

  const appendOnly = page
    .locator('.terminal-root section', { hasText: 'APPEND-ONLY' })
    .first();
  await expect(appendOnly).toContainText('Absence is not deletion');
  await expect(appendOnly).toContainText('A first import proves nothing');

  const lost = page.locator('.terminal-root section', { hasText: 'DELETED HISTORY WE STILL HOLD' }).first();
  await expect(lost).toContainText('Diary entries');
  await expect(lost).toContainText('the film or thread was removed from Letterboxd');
});

test('Data Profiles owns its mutations now that the old manager is gone', async ({ page }) => {
  await page.goto('/data?tab=profiles');

  await expect(page.getByText('▸ EVERYONE WE HAVE SYNCED', { exact: false })).toBeVisible();
  // The ASK panel is the request form itself, not a pointer at a page that no
  // longer exists.
  const ask = page.locator('.terminal-root section', { hasText: 'ASK FOR SOMEONE NEW' }).first();
  await expect(ask.getByRole('textbox', { name: 'Letterboxd username' })).toBeVisible();
  await expect(ask.getByRole('button', { name: 'ADD OR REQUEST' })).toBeVisible();
  await expect(ask.getByRole('link', { name: 'the profile manager' })).toHaveCount(0);

  const requestPromise = page.waitForRequest(
    (request) =>
      new URL(request.url()).pathname === '/profiles/requests' && request.method() === 'POST',
  );
  await ask.getByRole('textbox', { name: 'Letterboxd username' }).fill('somebody_new');
  await ask.getByRole('button', { name: 'ADD OR REQUEST' }).click();
  const request = await requestPromise;
  expect(request.postDataJSON()).toEqual({ username: 'somebody_new' });
});
