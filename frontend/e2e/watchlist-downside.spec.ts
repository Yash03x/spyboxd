import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * A queue ranked by upside alone reads as a list of safe bets. Where the crowd
 * genuinely splits, the downside is published beside the upside — and where it
 * does not, no downside note is invented to fill the space.
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

test('a divisive queue film shows both ends of the crowd, not just the upside', async ({ page }) => {
  await page.goto('/people?tab=one&subject=alpha');

  const panel = page
    .locator('.terminal-root section')
    .filter({ hasText: 'THEIR QUEUE, RANKED BY THE TRACKED GROUP' })
    .first();
  const row = panel.locator('div').filter({ hasText: 'Divisive Queue Entry' }).last();

  await expect(row).toContainText('31% rated it 4.5+');
  await expect(row).toContainText('22% rated it 2.0 or below');
});

test('a broadly liked film is not given a downside note it has not earned', async ({ page }) => {
  await page.goto('/people?tab=one&subject=alpha');

  const panel = page
    .locator('.terminal-root section')
    .filter({ hasText: 'THEIR QUEUE, RANKED BY THE TRACKED GROUP' })
    .first();
  const row = panel.locator('div').filter({ hasText: 'Queued Fixture Film' }).last();

  await expect(row).toContainText('42% rated it 4.5+');
  await expect(row).not.toContainText('rated it 2.0 or below');
});
