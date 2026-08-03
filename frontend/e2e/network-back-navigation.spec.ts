import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * The follow graph lives on People › The circle now. Two guarantees survive the
 * move: re-centring on somebody and coming back must leave a rendered graph
 * rather than an empty frame, and a failed request must explain itself instead
 * of returning null and leaving the tab blank.
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

test('re-centring the graph and going back leaves it rendered', async ({ page }) => {
  await page.goto('/people?tab=circle&subject=alpha');

  const panel = page.locator('section', { hasText: 'FOLLOW GRAPH' }).first();
  await expect(panel).toBeVisible();
  await expect(panel.getByRole('button', { name: /^@/ }).first()).toBeVisible();

  await panel.getByRole('button', { name: '@bravo', exact: true }).first().click();
  await expect(page).toHaveURL(/subject=bravo/);
  await expect(page.getByText('▸ FOLLOW GRAPH · @BRAVO', { exact: false })).toBeVisible();

  await page.goBack();

  // The header alone is not enough -- the graph itself has to come back, with
  // clickable nodes rather than an empty frame.
  await expect(page.getByText('▸ FOLLOW GRAPH · @ALPHA', { exact: false })).toBeVisible();
  await expect(panel.getByRole('button', { name: /^@/ }).first()).toBeVisible();
});

test('page content is actually painted, not just present in the DOM', async ({ page }) => {
  // Playwright's visibility check ignores opacity, so `toBeVisible` once passed
  // on a page users saw as blank: nested entrance animations each started at
  // opacity 0 and multiply down the tree. Assert the painted result.
  await page.goto('/people?tab=circle&subject=alpha');
  await expect(page.getByRole('heading', { name: 'People', level: 1 })).toBeVisible();

  const effectiveOpacity = await page.evaluate(() => {
    const heading = [...document.querySelectorAll('h1')].find(
      (node) => node.textContent?.trim() === 'People',
    );
    let element: HTMLElement | null = (heading as HTMLElement) ?? null;
    let product = 1;
    while (element && element !== document.documentElement) {
      product *= parseFloat(getComputedStyle(element).opacity);
      element = element.parentElement;
    }
    return product;
  });

  expect(effectiveOpacity).toBeGreaterThan(0.99);
});

test('a failed follow-graph request explains itself instead of rendering nothing', async ({
  page,
}) => {
  // The panel used to `return null` on error, so any failed request -- a token
  // refresh landing mid-navigation, a dropped connection -- left the page blank
  // with no way to recover, since the query does not retry.
  await page.route('**/api/profiles/*/follow-graph*', (route) =>
    route.fulfill({ status: 500, contentType: 'application/json', body: '{"detail":"boom"}' }),
  );

  await page.goto('/people?tab=circle&subject=alpha');

  await expect(page.getByRole('heading', { name: 'People', level: 1 })).toBeVisible();
  const panel = page.locator('section', { hasText: 'FOLLOW GRAPH' }).first();
  await expect(panel).toBeVisible();
  await expect(panel.getByText(/could not be loaded/i)).toBeVisible();
  await expect(panel.getByRole('button', { name: /try again/i })).toBeVisible();
  // Graded, not fatal: one dead panel must not take the tab with it.
  await expect(page.getByText('▸ MOST CONNECTED', { exact: false })).toBeVisible();
});
