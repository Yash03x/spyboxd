import { expect, test, type ConsoleMessage, type Page, type TestInfo } from '@playwright/test';

import { installApiMocks, MISSING_POSTER_URL } from './fixtures/api';

const runtimeErrors = new WeakMap<Page, string[]>();

function isExpectedMissingPosterError(message: ConsoleMessage): boolean {
  return message.text().includes('Failed to load resource: the server responded with a status of 404')
    && message.location().url === MISSING_POSTER_URL;
}

async function expectAccountControl(page: Page) {
  if ((page.viewportSize()?.width ?? 0) < 1024) {
    await page.getByRole('button', { name: 'Open navigation' }).click();
    await expect(page.getByRole('button', { name: 'Open user menu' })).toBeVisible();
    await page.getByRole('button', { name: 'Close navigation' }).click();
    return;
  }
  await expect(page.getByRole('button', { name: 'Open user menu' })).toBeVisible();
}

test.beforeEach(async ({ page }) => {
  const errors: string[] = [];
  runtimeErrors.set(page, errors);
  page.on('pageerror', (error) => errors.push(`pageerror: ${error.message}`));
  page.on('console', (message) => {
    if (message.type() === 'error' && !isExpectedMissingPosterError(message)) {
      errors.push(`console: ${message.text()}`);
    }
  });
  await installApiMocks(page);
});

test.afterEach(async ({ page }, testInfo: TestInfo) => {
  const errors = runtimeErrors.get(page) ?? [];
  if (errors.length > 0) {
    await testInfo.attach('runtime-errors', {
      body: errors.join('\n'),
      contentType: 'text/plain',
    });
  }
  expect(errors, 'The page must not emit console errors or uncaught exceptions').toEqual([]);
});

test('signed-in private dashboard renders the scoped data and navigates to My Profiles', async ({ page }) => {
  await page.goto('/dashboard');

  await expect(page).toHaveTitle(/Spyboxd/);
  await expect(page.getByRole('heading', { level: 1, name: 'Dashboard', exact: true })).toBeVisible();
  await expect(page.getByText('Monitored Profiles', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('10 profiles loaded')).toBeVisible();
  await expectAccountControl(page);

  const manageProfiles = page.getByRole('button', { name: 'Choose monitored profiles' });
  await expect(manageProfiles).toBeVisible();
  await manageProfiles.click();
  await expect(page).toHaveURL(/\/profiles$/);
  await expect(page.getByRole('heading', { level: 1, name: 'My Profiles', exact: true })).toBeVisible();
});

test('signed-in public homepage remains aggregate-only', async ({ page }) => {
  await page.goto('/');

  await expect(page.getByTestId('public-dashboard')).toBeVisible();
  await expect(page.getByRole('link', { name: 'Open My Dashboard' })).toBeVisible();
  await expect(page.getByText('@alpha', { exact: true })).toHaveCount(0);
  await expect(page.getByText('Most Active Profile', { exact: true })).toHaveCount(0);
});

test('profiles can be searched without hiding matching data', async ({ page }) => {
  await page.goto('/profiles');

  await expect(page.getByRole('heading', { level: 1, name: 'My Profiles', exact: true })).toBeVisible();
  await page.getByPlaceholder('Search profiles...').fill('charlie');
  const trackedGrid = page.getByTestId('tracked-profile-grid');
  await expect(trackedGrid.getByText('@charlie', { exact: true })).toBeVisible();
  await expect(page.getByText('1 of 10 tracked profiles')).toBeVisible();
  await expect(trackedGrid.getByText('@alpha', { exact: true })).toHaveCount(0);
});

test('a signed-in user can choose an existing profile from the catalog', async ({ page }) => {
  await page.goto('/profiles');

  await expect(page.getByText('10 monitored', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Stop monitoring bravo' }).click();
  await expect(page.getByText('9 monitored', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Monitor bravo' }).click();
  await expect(page.getByText('10 monitored', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Stop monitoring bravo' })).toBeVisible();
});

test('available-profile search is server-backed and reports the bounded result set', async ({ page }) => {
  const catalogRequests: URL[] = [];
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (url.pathname === '/profiles/catalog') catalogRequests.push(url);
  });

  await page.goto('/profiles');
  const catalog = page.getByRole('region', { name: 'Choose profiles to monitor' });
  await catalog.getByPlaceholder('Search available profiles...').fill('juliet');

  await expect(catalog.getByTestId('profile-catalog-result-summary')).toHaveText('1 matching synced profile');
  await expect(catalog.getByText(/^@juliet · /)).toBeVisible();
  await expect(catalog.getByText(/^@alpha · /)).toHaveCount(0);
  await expect.poll(() => catalogRequests.some((url) => (
    url.searchParams.get('search') === 'juliet'
      && url.searchParams.get('limit') === '100'
  ))).toBe(true);
});

test('a new Letterboxd username becomes a visible pending request', async ({ page }) => {
  await page.goto('/profiles');

  await page.getByPlaceholder('Letterboxd username').fill('newprofile');
  await page.getByRole('button', { name: 'Add or request' }).click();

  await expect(page.getByText('@newprofile', { exact: true })).toBeVisible();
  await expect(page.getByText('Awaiting review', { exact: true })).toBeVisible();
  await expect(page.getByText('Request sent. You can follow its status below.')).toBeVisible();
});

test('ordinary request history does not expose internal admin fields', async ({ page }) => {
  await page.goto('/profiles');

  await expect(page.getByText('@queuedprofile', { exact: true })).toBeVisible();
  await expect(page.getByText('Accepted for the next sync.', { exact: true })).toHaveCount(0);
  await expect(page.getByText(/Requester user_e2e/)).toHaveCount(0);
});

test('stopping tracking removes only the profile from the user set', async ({ page }) => {
  page.on('dialog', (dialog) => dialog.accept());
  await page.goto('/profiles');

  await page.getByRole('button', { name: 'Remove alpha from My Profiles' }).click();

  await expect(page.getByText('@alpha', { exact: true })).toHaveCount(0);
  await expect(page.getByText('9 of 9 tracked profiles')).toBeVisible();
  await expect(page.getByText(/shared data was not deleted/i)).toBeVisible();
});

test('compare changes a profile and applies the selected pair', async ({ page }) => {
  await page.goto('/compare');

  await expect(page.getByRole('heading', { name: 'Compare Profiles' })).toBeVisible();
  await expectAccountControl(page);
  const profileA = page.locator('label').filter({ hasText: 'Profile A' }).locator('select');
  await profileA.selectOption('charlie');
  await page.getByRole('button', { name: 'Compare', exact: true }).click();

  await expect(page).toHaveURL(/profiles=charlie/);
  await expect(page.getByRole('tabpanel', { name: 'Pair Dossier' })).toBeVisible();
  await expect(page.getByText('Who watched first?')).toBeVisible();
});

test('spy signal selector opens, remains visible, and updates the scan', async ({ page }) => {
  await page.goto('/spy-signals');

  await expect(page.getByRole('heading', { level: 1, name: 'Spy Signals', exact: true })).toBeVisible();
  const selector = page.getByRole('button', { name: /Profiles \(10 selected\)/ });
  await selector.click();
  const options = page.getByRole('group', { name: /Profiles \(10 selected\)/ });
  await expect(options).toBeVisible();

  await options.locator('label').filter({ hasText: 'juliet' }).getByRole('checkbox').uncheck();
  await expect(page.getByText('Profiles (9 selected)')).toBeVisible();
  await page.getByRole('button', { name: 'Scan Signals' }).click();

  await expect(page).toHaveURL(/gap_days=1/);
  await expect(page.getByText('Shared Fixture Film').first()).toBeVisible();
});

test('watch together selector stays in the viewport and broken posters fall back', async ({ page }) => {
  await page.goto('/watch-together');

  await expect(page.getByRole('heading', { level: 1, name: 'Watch Together' })).toBeVisible();
  const selector = page.getByRole('button', { name: 'Group profiles' });
  await selector.click();
  const panel = page.getByRole('group', { name: 'Group profiles' });
  await expect(panel).toBeVisible();

  const lastProfile = panel.getByText('juliet', { exact: true });
  await lastProfile.scrollIntoViewIfNeeded();
  await expect(lastProfile).toBeVisible();
  const panelBox = await panel.boundingBox();
  const viewport = page.viewportSize();
  expect(panelBox).not.toBeNull();
  expect(viewport).not.toBeNull();
  expect(panelBox!.x).toBeGreaterThanOrEqual(0);
  expect(panelBox!.x + panelBox!.width).toBeLessThanOrEqual(viewport!.width + 1);
  expect(panelBox!.y + panelBox!.height).toBeLessThanOrEqual(viewport!.height + 1);

  const echoOption = panel.getByText('echo', { exact: true }).locator('xpath=ancestor::label[1]');
  await echoOption.click();
  await expect(echoOption.getByRole('checkbox')).toBeChecked();
  await expect(selector).toContainText('5 selected');
  await page.keyboard.press('Escape');
  await expect(panel).toBeHidden();

  await expect(page.getByText('Fallback Fixture', { exact: true }).filter({ visible: true }).first()).toBeVisible();
  await expect(page.locator('img[src*="missing-poster"]')).toHaveCount(0);
  const brokenImages = await page.locator('main img').evaluateAll((images) => images.filter((image) => {
    const element = image as HTMLImageElement;
    return element.complete && element.naturalWidth === 0;
  }).length);
  expect(brokenImages).toBe(0);
});
