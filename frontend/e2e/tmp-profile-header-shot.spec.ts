import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

test('temp: capture profile header', async ({ page }) => {
  await installApiMocks(page);
  await page.goto('/analysis');
  const header = page.locator('section[aria-labelledby="profile-header-name"]');
  await expect(header).toBeVisible();
  await header.screenshot({ path: '/private/tmp/claude-501/-Users-yash-code-letterboxd-reviewer/262be126-72b7-4b9e-bb4e-39ee851542c2/scratchpad/profile-header.png' });
});
