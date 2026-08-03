import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * People merges Analysis, Compare and Network into one destination with four
 * tabs. The assertions below are mostly about *honesty*: the panels that stay
 * empty by design have to say what they are waiting for, and the ones that read
 * an export-only surface have to say that rather than reading as "nothing here".
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page, { isAdmin: true });
});

test('the three old destinations redirect into People', async ({ page }) => {
  for (const [from, tab] of [
    ['/analysis', 'one'],
    ['/compare', 'two'],
    ['/network', 'circle'],
  ] as const) {
    await page.goto(from);
    await expect(page).toHaveURL(new RegExp(`/people\\?tab=${tab}`));
  }
});

test('One person renders its panels and names the subject', async ({ page }) => {
  await page.goto('/people?tab=one&subject=alpha');

  await expect(page.getByRole('heading', { level: 1, name: 'People', exact: true })).toBeVisible();
  await expect(page.getByText('▸ @ALPHA', { exact: false })).toBeVisible();

  for (const title of [
    'THEIR FOUR FAVOURITES',
    'THEY KEEP GOING BACK',
    'WATCHED BUT NEVER RATED',
    'LOVED IT, SAID NOTHING',
    'GONE QUIET',
  ]) {
    await expect(page.getByText(`▸ ${title}`, { exact: false }).first()).toBeVisible();
  }
});

test('the subject is in the URL, so a person is linkable', async ({ page }) => {
  await page.goto('/people?tab=one');
  await page.getByRole('link', { name: '@bravo', exact: true }).click();

  await expect(page).toHaveURL(/subject=bravo/);
  await page.reload();
  await expect(page.getByText('▸ @BRAVO', { exact: false })).toBeVisible();
});

test('unrated films are shown as a hole in the evidence, with its size', async ({ page }) => {
  await page.goto('/people?tab=one&subject=alpha');

  const panel = page.locator('section', { hasText: 'WATCHED BUT NEVER RATED' }).first();
  await expect(panel.getByText('318', { exact: true })).toBeVisible();
  await expect(panel.getByText('UNRATED', { exact: true })).toBeVisible();
  // The number alone is not the point: every comparison skips these silently,
  // and the caveat is what says so.
  await expect(
    panel.getByText('Every star comparison in the product skips these', { exact: false }),
  ).toBeVisible();
});

test('a rating change states it needs two reads, not that nothing happened', async ({ page }) => {
  await page.goto('/people?tab=one&subject=alpha');

  const panel = page.locator('section', { hasText: 'CHANGED THEIR MIND ON A REWATCH' }).first();
  await expect(panel.getByText('Changed Fixture', { exact: false })).toBeVisible();
  await expect(panel.getByText('3.5 → 4.5', { exact: true })).toBeVisible();
  await expect(panel.getByText('+1.0', { exact: true })).toBeVisible();
});

test('Two people compares the pair and refuses a one-sided face-off', async ({ page }) => {
  await page.goto('/people?tab=two');

  await expect(page.getByText('▸ HEAD TO HEAD', { exact: false })).toBeVisible();
  await expect(page.getByText('▸ BIGGEST DISAGREEMENTS', { exact: false })).toBeVisible();
  await expect(page.getByText('▸ NEITHER HAS SEEN IT', { exact: false })).toBeVisible();

  // Lead share is meaningless without the volume baseline beside it.
  const headToHead = page.locator('section', { hasText: 'HEAD TO HEAD' }).first();
  await expect(headToHead.getByText('Gets there first', { exact: true })).toBeVisible();
  await expect(
    headToHead.getByText('their watch volume alone would produce', { exact: false }),
  ).toBeVisible();
});

test('The circle draws the ego graph and grades every edge', async ({ page }) => {
  await page.goto('/people?tab=circle&subject=alpha');

  await expect(page.getByText('▸ FOLLOW GRAPH', { exact: false })).toBeVisible();
  await expect(page.getByText('MUTUAL', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('NOT TRACKED', { exact: true })).toBeVisible();
});

test('an unfollow says it needs two reads before it can be inferred', async ({ page }) => {
  await page.goto('/people?tab=circle&subject=alpha');

  const panel = page.locator('section', { hasText: 'FOLLOWED AND UNFOLLOWED' }).first();
  await expect(
    panel.getByText('inferred from an edge disappearing between two authoritative reads', {
      exact: false,
    }),
  ).toBeVisible();
});

test('export-only panels say so rather than reading as empty', async ({ page }) => {
  await page.goto('/people?tab=circle&subject=alpha');

  const conversations = page.locator('section', { hasText: 'CONVERSATIONS' }).first();
  await expect(conversations.getByText('NEW', { exact: true })).toBeVisible();
  await expect(
    conversations.getByText('comments live in the official data export and cannot be scraped', {
      exact: false,
    }),
  ).toBeVisible();
});

test('Reach reports a rename as a cost, not as a history it never kept', async ({ page }) => {
  await page.goto('/people?tab=reach&subject=alpha');

  const panel = page.locator('section', { hasText: 'SURVIVES A RENAME' }).first();
  await expect(panel.getByText('Renamed in place, history kept').first()).toBeVisible();
  await expect(panel.getByText('Would look like a new account')).toBeVisible();
  await expect(
    panel.getByText('the row is updated, not versioned', { exact: false }),
  ).toBeVisible();
});

test('a follower count that was never read says so instead of showing zero', async ({ page }) => {
  await page.goto('/people?tab=reach&subject=alpha');

  const panel = page.locator('section', { hasText: 'FOLLOWERS AGAINST FOLLOWING' }).first();
  await expect(panel.getByText('1,284', { exact: true })).toBeVisible();
  await expect(
    panel.getByText('a profile with no reading has null on both, which is not the same as zero', {
      exact: false,
    }),
  ).toBeVisible();
});

test('the member card omits a field the profile never supplied', async ({ page }) => {
  await page.goto('/people?tab=reach&subject=alpha');

  const panel = page.locator('section', { hasText: 'MEMBER CARD' }).first();
  await expect(panel.getByText('Badge', { exact: true })).toBeVisible();
  await expect(panel.getByText('Patron', { exact: true })).toBeVisible();
  // Pronouns are export-only and this fixture supplies none, so the row is
  // absent rather than present and labelled "unknown".
  await expect(panel.getByText('Pronouns', { exact: true })).toHaveCount(0);
});
