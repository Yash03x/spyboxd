import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

test('an anonymous visitor is redirected from the app to sign in', async ({ page }) => {
  await installApiMocks(page, { authenticated: false });

  await page.goto('/');

  await expect(page).toHaveURL(/\/sign-in(?:\/|\?|$)/);
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible();
});

for (const path of ['/upload', '/users']) {
  test(`an anonymous visitor cannot bypass auth with ${path}`, async ({ page }) => {
    await installApiMocks(page, { authenticated: false });

    await page.goto(path);

    await expect(page).toHaveURL(/\/sign-in(?:\/|\?|$)/);
  });
}
