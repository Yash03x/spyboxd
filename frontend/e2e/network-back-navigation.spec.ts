import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * Opening a profile's deep dive from the network graph and pressing Back has to
 * return to a rendered graph. The report was that it came back blank.
 */
test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

test('returning from a deep dive re-renders the network graph', async ({ page }) => {
  await page.goto('/network');

  const panel = page.getByTestId('follow-network');
  await expect(panel).toBeVisible();

  // Centre a tracked profile, then open its deep dive from the centre.
  const centreNode = page.getByRole('button', { name: /^Centre the network on @/ }).first();
  await expect(centreNode).toBeVisible();
  await centreNode.click();

  const openDeepDive = page.getByRole('button', { name: /deep dive analysis$/ }).first();
  await expect(openDeepDive).toBeVisible();
  await openDeepDive.click();
  await expect(page).toHaveURL(/\/analysis\?profile=/);

  await page.goBack();

  await expect(page).toHaveURL(/\/network/);
  await expect(page.getByRole('heading', { name: 'Network', level: 1 })).toBeVisible();
  // The header alone is not enough — the graph panel itself must come back,
  // with clickable nodes rather than an empty frame.
  await expect(panel).toBeVisible();
  await expect(
    page.getByRole('button', { name: /^Centre the network on @/ }).first(),
  ).toBeVisible();
});

test('page content is actually painted, not just present in the DOM', async ({ page }) => {
  // Playwright's visibility check ignores opacity, so `toBeVisible` passed on a
  // page users saw as blank. Three nested entrance animations each started at
  // opacity 0 and multiply down the tree; when a route change stranded them
  // part-way the product reached ~0.02. Assert the painted result.
  const effectiveOpacity = () =>
    page.evaluate(() => {
      const heading = [...document.querySelectorAll('h1')].find(
        (node) => node.textContent?.trim() === 'Network',
      );
      let element: HTMLElement | null = heading ?? null;
      let product = 1;
      while (element && element !== document.documentElement) {
        product *= parseFloat(getComputedStyle(element).opacity);
        element = element.parentElement;
      }
      return product;
    });

  await page.goto('/network');
  // Checked immediately, not polled. Polling waits for the entrance animation
  // to finish, which is exactly the assumption that broke: an animation clock
  // that never advances (a background tab freezes it at its first keyframe)
  // leaves the page at whatever that keyframe says. No ancestor may start from
  // transparent, so the content is already painted before anything animates.
  expect(await effectiveOpacity()).toBeGreaterThan(0.99);

  await page.getByRole('button', { name: /^Centre the network on @/ }).first().click();
  await page.getByRole('button', { name: /deep dive analysis$/ }).first().click();
  await expect(page).toHaveURL(/\/analysis\?profile=/);
  await page.goBack();

  await expect(page).toHaveURL(/\/network/);
  expect(await effectiveOpacity()).toBeGreaterThan(0.99);
});

test('navigation chrome is painted, not only the page content', async ({ page }) => {
  // The first fix covered the shell and the view roots but left the sidebar and
  // top bar fading in from `opacity: 0`. On production, with the tab
  // backgrounded so no animation clock advances, the content was fully painted
  // and the navigation was at 0 - invisible until the tab was focused.
  await page.goto('/network');

  const chromeOpacity = () =>
    page.evaluate(() =>
      ['nav', 'main > header'].map((selector) => {
        const node = document.querySelector(selector);
        if (!node) return { selector, opacity: null as number | null };
        let element: HTMLElement | null = node as HTMLElement;
        let product = 1;
        while (element && element !== document.documentElement) {
          product *= parseFloat(getComputedStyle(element).opacity);
          element = element.parentElement;
        }
        return { selector, opacity: product };
      }),
    );

  for (const entry of await chromeOpacity()) {
    if (entry.opacity === null) continue;
    expect(entry.opacity, `${entry.selector} must be painted`).toBeGreaterThan(0.99);
  }
});

test('a failed follow-graph request explains itself instead of rendering nothing', async ({
  page,
}) => {
  // The panel used to `return null` on error, so any failed request -- a token
  // refresh landing mid-navigation, a dropped connection -- left the page blank
  // with no way to recover, since the query does not retry.
  await page.route('**/api/follow-graph/mutuals*', (route) =>
    route.fulfill({ status: 500, contentType: 'application/json', body: '{"detail":"boom"}' }),
  );

  await page.goto('/network');

  await expect(page.getByRole('heading', { name: 'Network', level: 1 })).toBeVisible();
  const panel = page.getByTestId('follow-network');
  await expect(panel).toBeVisible();
  await expect(panel.getByText(/could not be loaded/i)).toBeVisible();
  await expect(panel.getByRole('button', { name: /try again/i })).toBeVisible();
});
