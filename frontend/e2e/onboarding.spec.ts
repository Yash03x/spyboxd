import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

test('an empty profile set guides the user to My Profiles', async ({ page }) => {
  await installApiMocks(page, { profileCount: 0 });

  await page.goto('/dashboard');

  await expect(page.getByRole('heading', { name: 'Choose your first monitored profile' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Choose or request a profile' })).toBeVisible();
});

test('one tracked profile explains how to unlock pair features', async ({ page }) => {
  await installApiMocks(page, { profileCount: 1 });

  await page.goto('/dashboard');

  await expect(page.getByRole('heading', { name: 'Add one more profile for Spy Signals' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Add or request a profile' })).toBeVisible();
});

test('a synced signup profile is identified and cannot be removed', async ({ page }) => {
  await installApiMocks(page, {
    profileCount: 1,
    letterboxdUsername: 'alpha',
    primaryProfileStatus: 'tracked',
  });

  await page.goto('/profiles?onboarding=1');

  const identity = page.getByTestId('primary-profile-status');
  await expect(identity.getByText('@alpha', { exact: true })).toBeVisible();
  await expect(identity.getByText(/synced and included/i)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Your Letterboxd profile alpha' })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Remove alpha from My Profiles' })).toHaveCount(0);
  await expect(page.getByTestId('tracked-profile-grid').getByText('Your profile', { exact: true })).toBeVisible();
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
  await expect(identity.getByText(/automatically requested this profile/i)).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Request another profile' })).toBeVisible();
});

test('a legacy account without a canonical username receives a repair message', async ({ page }) => {
  await installApiMocks(page, {
    profileCount: 0,
    letterboxdUsername: null,
    primaryProfileStatus: 'unconfigured',
  });

  await page.goto('/profiles?onboarding=1');

  await expect(page.getByRole('heading', { name: 'Letterboxd username not linked' })).toBeVisible();
  await expect(page.getByText(/pre-existing account has no Letterboxd username linked/i)).toBeVisible();
});
