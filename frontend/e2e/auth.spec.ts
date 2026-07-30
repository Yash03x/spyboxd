import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

test('the aggregate dashboard is the anonymous landing page', async ({ page }) => {
  await installApiMocks(page, { authenticated: false });

  const apiRequests: Array<{ path: string; authorization?: string }> = [];
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (url.protocol === 'http:' && url.port === '8000' && ['127.0.0.1', 'localhost'].includes(url.hostname)) {
      apiRequests.push({
        path: url.pathname,
        authorization: request.headers().authorization,
      });
    }
  });

  await page.goto('/');

  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByTestId('public-dashboard')).toBeVisible();
  await expect(page.getByRole('heading', { name: /without exposing anyone's profile/i })).toBeVisible();
  const signInLink = page.getByRole('link', { name: 'Sign in to monitor profiles' });
  await expect(signInLink).toBeVisible();
  await expect(signInLink).toHaveAttribute('href', '/sign-in?redirect_url=%2Fprofiles');
  await expect(page.getByRole('link', { name: 'Sign in for private tools' }))
    .toHaveAttribute('href', '/sign-in?redirect_url=%2Fprofiles');
  await expect(page.getByText('@alpha', { exact: true })).toHaveCount(0);
  expect(apiRequests.length).toBeGreaterThanOrEqual(1);
  expect(apiRequests.every(({ path }) => path === '/api/public/dashboard')).toBe(true);
  expect(apiRequests.every(({ authorization }) => authorization === undefined)).toBe(true);
});

for (const path of ['/dashboard', '/profiles', '/analysis', '/compare', '/spy-signals', '/watch-together', '/u/alpha']) {
  test(`an anonymous visitor cannot bypass auth with ${path}`, async ({ page }) => {
    await installApiMocks(page, { authenticated: false });

    await page.goto(path);

    await expect(page).toHaveURL(/\/sign-in(?:\/|\?|$)/);
  });
}
