import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * The candidate panel counted the group signals — "Already watched 1", "Liked
 * by 1" — while the names behind those counts sat unread in the payload. For a
 * group pick the names are the point: whether the one person who has seen it
 * would sit through it again is not something a count can answer.
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

test('group signals name who watched and who liked, not only how many', async ({ page }) => {
  await page.goto('/watch-together');

  await page.getByText('Seen By One Fixture').locator('visible=true').first().click();

  const panel = page.getByRole('heading', { name: 'Group signals' }).locator('..');
  await expect(panel).toContainText('@charlie');
  // And who it would still be new to, which is the other half of the decision.
  await expect(panel).toContainText('New to @alpha, @bravo');
});
