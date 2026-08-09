import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

test('an empty profile set guides the user to Data', async ({ page }) => {
  await installApiMocks(page, { profileCount: 0 });

  await page.goto('/overview');

  await expect(page.getByRole('heading', { name: 'Choose your first monitored profile' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'CHOOSE OR REQUEST A PROFILE' })).toBeVisible();
});

test('one tracked profile explains how to unlock pair features', async ({ page }) => {
  await installApiMocks(page, { profileCount: 1 });

  await page.goto('/overview');

  // Overlap and star distance are both pair measures, so the panel that needs
  // two says so where the answer would have been rather than rendering an
  // empty grid the reader has to interpret.
  //
  // Scoped to that panel: several empty states now legitimately offer the same
  // next step, which is right for a reader and a strict-mode violation for an
  // unscoped locator.
  const pairPanel = page
    .locator('.terminal-root section', { hasText: 'WHO WATCHES WITH WHOM' })
    .first();
  await expect(pairPanel.getByRole('heading', { name: 'Two profiles are needed' })).toBeVisible();
  await expect(pairPanel.getByRole('link', { name: 'CHOOSE WHO TO MONITOR' })).toBeVisible();
});

test('a synced signup profile is identified and cannot be removed', async ({ page }) => {
  await installApiMocks(page, {
    profileCount: 1,
    letterboxdUsername: 'alpha',
    primaryProfileStatus: 'tracked',
  });

  // The retired manager path still routes to the new home, onboarding flag
  // intact -- the sign-up force-redirect depends on it.
  await page.goto('/profiles?onboarding=1');
  await expect(page).toHaveURL(/\/data\?tab=profiles&onboarding=1/);

  const identity = page.getByTestId('primary-profile-status');
  await expect(identity.getByText('@alpha', { exact: true })).toBeVisible();
  await expect(identity.getByText(/part of your monitored set/i)).toBeVisible();
  // The primary profile is marked in both the library and the catalog, and
  // carries no stop button in either.
  await expect(page.getByText('yours to keep', { exact: true }).first()).toBeVisible();
  await expect(page.getByRole('button', { name: /Stop monitoring alpha/ })).toHaveCount(0);
});

test('a missing signup profile explains its automatic sync request', async ({ page }) => {
  await installApiMocks(page, {
    profileCount: 0,
    letterboxdUsername: 'new_viewer',
    primaryProfileStatus: 'pending',
  });

  await page.goto('/profiles?onboarding=1');

  const identity = page.getByTestId('primary-profile-status');
  await expect(identity.getByText('@new_viewer', { exact: true })).toBeVisible();
  await expect(identity.getByText(/requested automatically/i)).toBeVisible();
  await expect(
    page.locator('.terminal-root section', { hasText: 'ASK FOR SOMEONE NEW' }).first(),
  ).toBeVisible();
});

test('a legacy account without a canonical username receives a repair message', async ({ page }) => {
  await installApiMocks(page, {
    profileCount: 0,
    letterboxdUsername: null,
    primaryProfileStatus: 'unconfigured',
  });

  await page.goto('/profiles?onboarding=1');

  const identity = page.getByTestId('primary-profile-status');
  await expect(identity.getByText('no username linked', { exact: true })).toBeVisible();
  await expect(identity.getByText(/ask the administrator to repair the identity/i)).toBeVisible();
});
