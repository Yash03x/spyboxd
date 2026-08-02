import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * `cadence` shipped to production computed, serialised and typed — and with no
 * component reading it, so the API answered with a weekday breakdown that
 * nothing on the page displayed. The same failure as the semantic-neighbors
 * panel, arrived at from the opposite direction: there the UI existed and the
 * data was empty, here the data existed and the UI was missing.
 *
 * These assertions are about rendering, not arithmetic: the weekday maths is
 * covered in `backend/tests/test_profile_stats.py`.
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

test('the watching rhythm panel renders the weekday breakdown it is given', async ({ page }) => {
  await page.goto('/analysis');

  const heading = page.getByRole('heading', { name: 'Watching rhythm' });
  await expect(heading).toBeVisible();

  const panel = heading.locator('..').locator('..');
  // Scoped to the chart: 'Sat' also appears in the sentence below it, and the
  // point here is that the week itself is drawn.
  const weekdays = panel.getByTestId('cadence-weekdays');
  // Every weekday keeps its slot, so a quiet day reads as quiet rather than
  // vanishing and shifting the week along.
  for (const day of ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']) {
    await expect(weekdays.getByText(day, { exact: true })).toBeVisible();
  }
  await expect(weekdays.getByText('123', { exact: true })).toBeVisible();

  await expect(panel).toContainText('Most often a Sat');
  await expect(panel).toContainText('301 days with an entry');
});

test('a long silence is named, since a run of quiet weeks is not the same as a slow one', async ({ page }) => {
  await page.goto('/analysis');

  const panel = page.getByRole('heading', { name: 'Watching rhythm' }).locator('..').locator('..');

  await expect(panel).toContainText('Longest silence: 41 days');
  await expect(panel).toContainText('2024-05-26');
});
