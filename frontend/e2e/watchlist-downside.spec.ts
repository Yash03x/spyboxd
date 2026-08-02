import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * `_crowd_shape` has always returned both ends of the histogram — the share at
 * 4.5+ and the share at 2.0 and below — and only the ceiling was ever rendered.
 * A queue row reading "31% rated it 4.5+" and nothing else describes a film
 * with no downside, which is not what the data said: 22% of the same crowd
 * rated it 2.0 or below.
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

test('a divisive queue film shows both ends of the crowd, not just the upside', async ({ page }) => {
  await page.goto('/analysis');

  const row = page.locator('li').filter({ hasText: 'Divisive Queue Entry' }).first();
  await expect(row).toBeVisible();
  await expect(row).toContainText('31% rated it 4.5+');
  await expect(row).toContainText('22% rated it 2.0 or below');
});

test('a broadly liked film is not given a downside note it has not earned', async ({ page }) => {
  await page.goto('/analysis');

  const row = page.locator('li').filter({ hasText: 'Queued Fixture Film' }).first();
  await expect(row).toContainText('42% rated it 4.5+');
  // Its floor is 3%; noting that would be noise dressed as a warning.
  await expect(row).not.toContainText('rated it 2.0 or below');
});
