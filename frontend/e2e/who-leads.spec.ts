import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * `directional_leader` was computed from the first release and rendered by
 * nothing, so the answer existed and nobody could read it. Rendering the bare
 * winner would have been worse than the silence: whoever watches more reaches a
 * shared film first for no reason but volume, and across the tracked library
 * that accounts for about a fifth of the variation in who leads. The number
 * only means something beside its baseline.
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

test('the leader is shown against the share of watching that would explain it', async ({ page }) => {
  await page.goto('/compare?tab=dossier');

  const heading = page.getByRole('heading', { name: 'Who gets there first' });
  await expect(heading).toBeVisible();

  const panel = heading.locator('..').locator('..');
  await expect(panel).toContainText('@alpha');
  await expect(panel).toContainText('64%');
  // The baseline is the point: 64% of the leads on 24% of the watching.
  await expect(panel).toContainText('24%');
  await expect(panel).toContainText('they genuinely get there earlier');
  await expect(panel).toContainText('50 films they both dated, days apart');
});
