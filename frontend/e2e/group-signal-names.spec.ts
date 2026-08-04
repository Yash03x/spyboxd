import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * "Seen by 1" is a count; "@charlie has seen it, it is new to @alpha and
 * @bravo" is a decision. The second half — who it would still be new to — is
 * the part a room actually acts on.
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

test('group signals name who watched and who it is new to, not only how many', async ({ page }) => {
  await page.goto('/tonight?tab=picks');

  const shortlist = page.locator('.terminal-root section', { hasText: "TONIGHT'S SHORTLIST" }).first();
  await shortlist.getByRole('link', { name: /Seen By One Fixture/ }).click();

  const why = page.locator('.terminal-root section', { hasText: /▸ WHY .+ FITS/ }).first();
  await expect(why).toContainText('@charlie');
  await expect(why).toContainText('New to @alpha, @bravo');
});
