import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

test('a profile snapshot separates watched films from expressed opinions', async ({ page }) => {
  await page.goto('/u/alpha');

  const snapshot = page.locator('section', { hasText: '@alpha' });
  await expect(snapshot.getByText('1,200', { exact: true })).toBeVisible();
  await expect(snapshot.getByText('Opinion coverage', { exact: true })).toBeVisible();
  await expect(snapshot.getByText('900 rated · 180 liked', { exact: true })).toBeVisible();
});
