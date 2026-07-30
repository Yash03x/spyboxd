import { expect, test, type Page } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

const publicDashboardUrl = /^http:\/\/(?:127\.0\.0\.1|localhost):8000\/api\/public\/dashboard$/;

async function expectPublicAuthControl(page: Page, authenticated: boolean) {
  if (authenticated) {
    await expect(page.getByRole('button', { name: 'Sign out', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Open user menu' })).toBeVisible();
    return;
  }
  await expect(page.getByRole('link', { name: 'Create account' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Sign in to monitor profiles' })).toBeVisible();
}

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
  const createAccountLink = page.getByRole('link', { name: 'Create account' });
  await expect(createAccountLink).toHaveAttribute('href', '/sign-up');
  await expect(signInLink).toBeVisible();
  await expect(signInLink).toHaveAttribute('href', '/sign-in?redirect_url=%2Fprofiles');
  await expect(page.getByRole('link', { name: 'Sign in for private tools' }))
    .toHaveAttribute('href', '/sign-in?redirect_url=%2Fprofiles');
  await expect(page.getByText('@alpha', { exact: true })).toHaveCount(0);
  expect(apiRequests.length).toBeGreaterThanOrEqual(1);
  expect(apiRequests.every(({ path }) => path === '/api/public/dashboard')).toBe(true);
  expect(apiRequests.every(({ authorization }) => authorization === undefined)).toBe(true);

  await signInLink.click();
  await expect(page).toHaveURL(/\/sign-in(?:\/|\?|$)/);
  await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible();
  await expect.poll(() => page.evaluate(() => getComputedStyle(document.documentElement).colorScheme))
    .toContain('dark');
});

test('sign-up uses one required Letterboxd username as the Spyboxd identity', async ({ page }) => {
  await installApiMocks(page, { authenticated: false });

  await page.goto('/sign-up');

  await expect(page.getByRole('heading', {
    level: 1,
    name: 'Your Letterboxd username is your Spyboxd username.',
  })).toBeVisible();
  await expect(page.getByText(/automatically monitor it if it is already synced/i)).toBeVisible();
  const usernameInput = page.getByRole('textbox', { name: 'Letterboxd username' });
  await expect(usernameInput).toBeVisible();
  await expect(usernameInput).toHaveAttribute('required', '');
  await expect(usernameInput).toHaveAttribute('minlength', '2');
  await expect(usernameInput).toHaveAttribute('maxlength', '15');
  await expect(usernameInput).toHaveAttribute('pattern', '[A-Za-z0-9_]{2,15}');
  await expect(page.locator('[data-force-redirect-url="/profiles?onboarding=1"]')).toBeAttached();
});

for (const authenticated of [false, true]) {
  const authState = authenticated ? 'signed-in' : 'anonymous';

  test(`the ${authState} public auth header remains available while aggregate data loads`, async ({ page }) => {
    await installApiMocks(page, { authenticated });
    let releaseRequest!: () => void;
    const requestGate = new Promise<void>((resolve) => {
      releaseRequest = resolve;
    });
    await page.route(publicDashboardUrl, async (route) => {
      await requestGate;
      await route.fallback();
    });

    await page.goto('/');

    await expectPublicAuthControl(page, authenticated);
    await expect(page.getByText('Loading Spyboxd totals…')).toBeVisible();

    releaseRequest();
    await expect(page.getByRole('heading', { name: /without exposing anyone's profile/i })).toBeVisible();
  });

  test(`the ${authState} public auth header remains available when aggregate data fails`, async ({ page }) => {
    await installApiMocks(page, { authenticated });
    await page.route(publicDashboardUrl, (route) => (
      route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Unavailable' }) })
    ));

    await page.goto('/');

    await expectPublicAuthControl(page, authenticated);
    await expect(page.getByText('The public dashboard could not be loaded.')).toBeVisible();
  });
}

for (const path of ['/dashboard', '/profiles', '/analysis', '/compare', '/spy-signals', '/watch-together', '/u/alpha']) {
  test(`an anonymous visitor cannot bypass auth with ${path}`, async ({ page }) => {
    await installApiMocks(page, { authenticated: false });

    await page.goto(path);

    await expect(page).toHaveURL(/\/sign-in(?:\/|\?|$)/);
  });
}
