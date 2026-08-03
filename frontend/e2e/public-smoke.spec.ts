import { expect, test, type ConsoleMessage, type Locator, type Page, type TestInfo } from '@playwright/test';

import { installApiMocks, MISSING_POSTER_URL, profileAnalysis } from './fixtures/api';

const runtimeErrors = new WeakMap<Page, string[]>();

function isExpectedMissingPosterError(message: ConsoleMessage): boolean {
  return message.text().includes('Failed to load resource: the server responded with a status of 404')
    && message.location().url === MISSING_POSTER_URL;
}

async function expectAccountControl(page: Page) {
  const signOut = page.getByRole('button', { name: 'Sign out', exact: true });
  await expect(signOut).toBeVisible();
  await expectInsideViewport(page, signOut);
  // The redesigned sections keep the account control in the status bar at
  // every width. The not-yet-migrated views still hide theirs behind the
  // mobile navigation drawer, so both shells are accepted here.
  const drawerToggle = page.getByRole('button', { name: 'Open navigation' });
  if ((page.viewportSize()?.width ?? 0) < 1024 && (await drawerToggle.count()) > 0) {
    await drawerToggle.click();
    await expect(page.getByRole('button', { name: 'Open user menu' })).toBeVisible();
    await page.getByRole('button', { name: 'Close navigation' }).click();
    return;
  }
  await expect(page.getByRole('button', { name: 'Open user menu' })).toBeVisible();
}

async function expectInsideViewport(page: Page, locator: Locator) {
  await expect.poll(async () => {
    const viewport = page.viewportSize();
    const box = await locator.boundingBox();
    if (!viewport || !box) return false;
    return box.x >= 0
      && box.y >= 0
      && box.x + box.width <= viewport.width
      && box.y + box.height <= viewport.height;
  }).toBe(true);
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

test('Overview renders the scoped data and links on to the rest of the product', async ({ page }) => {
  await page.goto('/overview');

  await expect(page).toHaveTitle(/Spyboxd/);
  await expect(page.getByRole('heading', { level: 1, name: 'Overview', exact: true })).toBeVisible();
  await expect(page.getByText('10 PROFILES', { exact: false }).first()).toBeVisible();
  await expect(page.getByText('▸ EVERYONE WE ARE WATCHING', { exact: false })).toBeVisible();
  await expectAccountControl(page);

  // The rail is the way on: Data still lives at its pre-redesign path until
  // that section moves across, and the link has to resolve either way.
  const dataSection = page.getByRole('link', { name: '06 Data' });
  await expect(dataSection).toBeVisible();
  await dataSection.click();
  await expect(page).toHaveURL(/\/(data|profiles)$/);
});

test('private workspace sign out returns to the anonymous dashboard', async ({ page }) => {
  await page.goto('/overview');

  const signOut = page.getByRole('button', { name: 'Sign out', exact: true });
  await expect(signOut).toBeVisible();
  await expectInsideViewport(page, signOut);
  await signOut.click();

  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole('link', { name: 'Sign in to monitor profiles' })).toBeVisible();
});

test('insight workspace sign out returns to the anonymous dashboard', async ({ page }) => {
  await page.goto('/compare');

  const signOut = page.getByRole('button', { name: 'Sign out', exact: true });
  await expect(signOut).toBeVisible();
  await expectInsideViewport(page, signOut);
  await signOut.click();

  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole('link', { name: 'Sign in to monitor profiles' })).toBeVisible();
});

test('signed-in public homepage remains aggregate-only', async ({ page }) => {
  await page.goto('/');

  await expect(page.getByTestId('public-dashboard')).toBeVisible();
  await expect(page.getByRole('link', { name: 'Open My Dashboard' })).toBeVisible();
  const signOut = page.getByRole('button', { name: 'Sign out', exact: true });
  await expect(signOut).toBeVisible();
  await expectInsideViewport(page, signOut);
  await expect(page.getByRole('button', { name: 'Open user menu' })).toBeVisible();
  await expect(page.getByText('@alpha', { exact: true })).toHaveCount(0);
  await expect(page.getByText('Most Active Profile', { exact: true })).toHaveCount(0);

  await signOut.click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole('link', { name: 'Sign in to monitor profiles' })).toBeVisible();
});

test('watching activity identifies month-to-date events and excludes them from the completed-month average', async ({ page }) => {
  await page.goto('/');

  const activity = page.locator('section', { hasText: 'ACTIVITY, MONTH BY MONTH' }).first();
  await expect(activity).toBeVisible();

  // A month still in progress is not a month with less watching in it. Both
  // the exclusion and the number of months the average was taken over are
  // stated, so the figure cannot be read as covering the partial month too.
  await expect(activity.getByText(
    'July 2026 is month to date and is excluded from the completed-month average, which is taken over 2 completed months.',
    { exact: true },
  )).toBeVisible();
  await expect(activity.getByText('15.0', { exact: true })).toBeVisible();
  await expect(activity.getByText('WATCHES / MONTH', { exact: true })).toBeVisible();
  await expect(activity.getByText('12.0', { exact: true })).toBeVisible();
  await expect(activity.getByText('UNIQUE FILMS / MONTH', { exact: true })).toBeVisible();

  // Each bar carries the figures behind it, so the chart needs no legend and
  // no axis to be readable.
  await expect(
    activity.getByLabel('July 2026, month to date: 90 watch events; 70 unique films; average rating 3.9'),
  ).toBeVisible();
});
test('terminal panels are flat: no blur, no shadow, nothing slower than 120ms', async ({ page }) => {
  await page.goto('/people?tab=one&subject=alpha');

  const panels = page.locator('.terminal-root section');
  expect(await panels.count()).toBeGreaterThan(5);

  const styles = await panels.evaluateAll((elements) =>
    elements.map((element) => {
      const computed = window.getComputedStyle(element);
      return {
        backdropFilter: computed.backdropFilter,
        boxShadow: computed.boxShadow,
        borderRadius: computed.borderRadius,
        transitionSeconds: Math.max(
          ...computed.transitionDuration.split(',').map((value) => parseFloat(value) || 0),
        ),
      };
    }),
  );

  for (const style of styles) {
    expect(style.backdropFilter).toBe('none');
    expect(style.boxShadow).toBe('none');
    expect(style.borderRadius).toBe('0px');
    // "No transitions longer than 120ms anywhere in the product."
    expect(style.transitionSeconds).toBeLessThanOrEqual(0.12);
  }
});

test('a shared-film review keeps spoiler prose hidden until an accessible reveal', async ({ page }) => {
  await page.goto('/people?tab=two');

  const panel = page.locator('.terminal-root section').filter({ hasText: 'THE SAME FILM' }).first();
  const spoilerText = panel.getByText(
    'The identity loop changes how every earlier scene reads.',
    { exact: true },
  );
  const reveal = panel.getByRole('button', {
    name: "Reveal spoiler review for alpha's review of Predestination (2014)",
  });

  await expect(spoilerText).toBeHidden();
  await expect(reveal).toHaveAttribute('aria-expanded', 'false');

  await reveal.click();
  await expect(spoilerText).toBeVisible();
  await expect(
    panel.getByRole('button', {
      name: "Hide spoiler review for alpha's review of Predestination (2014)",
    }),
  ).toHaveAttribute('aria-expanded', 'true');
});

test('one written review is a spotlight, not a dropped face-off', async ({ page }) => {
  await page.goto('/people?tab=two');

  // The pair fixture has prose on one side only. Showing nothing would lose the
  // review entirely; showing it as a face-off would claim a second one exists.
  await expect(page.getByText('▸ THE SAME FILM, ONE REVIEW', { exact: false })).toBeVisible();
  const panel = page.locator('.terminal-root section').filter({ hasText: 'THE SAME FILM' }).first();
  // The side that wrote nothing is labelled as such rather than left blank.
  await expect(panel.getByText('@bravo · 5.0★ · no written review', { exact: true })).toBeVisible();
  await expect(panel.getByText('No written review', { exact: true })).toBeVisible();
});

test('coverage notes appear only when the import actually reported one', async ({ page }) => {
  let limitations: string[] = [];
  await page.route(/^http:\/\/(?:127\.0\.0\.1|localhost):8000\/profiles\/[^/]+\/analysis$/, (route) => (
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...profileAnalysis,
        data_coverage: {
          ...profileAnalysis.data_coverage,
          summary: 'RSS-only partial coverage.',
          limitations,
        },
      }),
    })
  ));

  await page.goto('/people?tab=one&subject=alpha');

  // An empty "what is missing" heading reads as a fact we failed to fetch,
  // which is the opposite of what the panel is for.
  const heading = page.getByText('▸ WHAT THIS IMPORT COULD NOT REACH', { exact: false });
  await expect(heading).toHaveCount(0);

  limitations = [
    'RSS-only data can omit older diary entries.',
    'This partial import does not include the watchlist.',
  ];
  await page.reload();

  await expect(heading).toBeVisible();
  const panel = page
    .locator('.terminal-root section')
    .filter({ hasText: 'WHAT THIS IMPORT COULD NOT REACH' })
    .first();
  await expect(panel).toContainText('RSS-only data can omit older diary entries.');
  await expect(panel).toContainText('This partial import does not include the watchlist.');
});

test('Two people changes a profile and recomputes the pair', async ({ page }) => {
  await page.goto('/people?tab=two');

  await expect(page.getByRole('heading', { level: 1, name: 'People', exact: true })).toBeVisible();
  await expectAccountControl(page);

  await page.getByRole('link', { name: '@charlie', exact: true }).click();

  await expect(page).toHaveURL(/profiles=charlie/);
  await expect(page.getByText('▸ HEAD TO HEAD', { exact: false })).toBeVisible();
  // Lead share without its volume baseline is a number that means nothing.
  await expect(page.getByText('Gets there first', { exact: true })).toBeVisible();
});

test('the Overlaps profile chips stay visible and rescan on click', async ({ page }) => {
  await page.goto('/overlaps');

  await expect(page.getByRole('heading', { level: 1, name: 'Overlaps', exact: true })).toBeVisible();

  // The selection is a permanently visible row rather than a dialog: it is the
  // input to every panel below it, so hiding it behind a click made the tab's
  // most important control the least reachable one.
  const juliet = page.getByRole('link', { name: '@juliet', exact: true });
  await expect(juliet).toBeVisible();
  await juliet.click();

  // Selection lives in the URL so the tab is linkable and survives a reload.
  await expect(page).toHaveURL(/profiles=juliet/);
  await expect(page.getByText('Shared Fixture Film').first()).toBeVisible();
});

test('Tonight keeps its selection in the viewport and never paints a broken poster', async ({
  page,
}) => {
  await page.goto('/tonight?tab=picks');

  await expect(page.getByRole('heading', { level: 1, name: 'Tonight', exact: true })).toBeVisible();

  // The selection is a permanently visible row rather than a dialog, so the
  // "does it fit on screen" question is about the row itself.
  const juliet = page.getByRole('link', { name: '@juliet', exact: true });
  await expect(juliet).toBeVisible();
  const box = await juliet.boundingBox();
  const viewport = page.viewportSize();
  expect(box).not.toBeNull();
  expect(viewport).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(viewport!.width + 1);

  await juliet.click();
  await expect(page).toHaveURL(/profiles=juliet/);

  // A poster URL that 404s falls back to the striped placeholder rather than
  // painting a torn icon: a stale poster path is ours to absorb.
  await expect(page.locator('img[src*="missing-poster"]')).toHaveCount(0);
  const brokenImages = await page.locator('img').evaluateAll((images) =>
    images.filter((image) => {
      const element = image as HTMLImageElement;
      return element.complete && element.naturalWidth === 0;
    }).length,
  );
  expect(brokenImages).toBe(0);
});
