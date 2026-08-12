import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

test('Tonight pick decisions are accessible, URL-backed, and request the selected mode', async ({
  page,
}) => {
  await page.goto('/tonight?tab=picks');

  const decision = page.getByRole('group', { name: 'Pick decision' });
  const watchlist = decision.getByRole('link', { name: 'WATCHLIST FIT', exact: true });
  const unseen = decision.getByRole('link', { name: 'UNSEEN BY ALL', exact: true });
  const blindSpot = decision.getByRole('link', { name: 'ONE PERSON LOVES', exact: true });

  await expect(decision).toBeVisible();
  await expect(watchlist).toHaveAttribute('aria-current', 'true');
  await expect(unseen).toBeVisible();
  await expect(blindSpot).toBeVisible();

  const unseenRequest = page.waitForRequest((request) => {
    const url = new URL(request.url());
    return url.pathname === '/api/watch-together' && url.searchParams.get('mode') === 'unseen_pick';
  });
  await unseen.click();
  await unseenRequest;
  await expect(page).toHaveURL(/(?:\?|&)mode=unseen_pick(?:&|$)/);
  await expect(unseen).toHaveAttribute('aria-current', 'true');
  await expect(page.getByText('Only films nobody in the room has watched.', { exact: false })).toBeVisible();

  const blindSpotRequest = page.waitForRequest((request) => {
    const url = new URL(request.url());
    return url.pathname === '/api/watch-together'
      && url.searchParams.get('mode') === 'collective_blind_spots';
  });
  await blindSpot.click();
  await blindSpotRequest;
  await expect(page).toHaveURL(/(?:\?|&)mode=collective_blind_spots(?:&|$)/);
  await expect(blindSpot).toHaveAttribute('aria-current', 'true');
  await expect(page.getByText('One person in the room liked it', { exact: false })).toBeVisible();

  const dimensions = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);

  await page.reload();
  await expect(decision).toBeVisible();
  await expect(blindSpot).toHaveAttribute('aria-current', 'true');
});
