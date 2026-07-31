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
  if ((page.viewportSize()?.width ?? 0) < 1024) {
    await page.getByRole('button', { name: 'Open navigation' }).click();
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

test('private workspace sign out returns to the anonymous dashboard', async ({ page }) => {
  await page.goto('/dashboard');

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

  const activityChart = page.getByRole('region', { name: 'Watching Activity' });
  await expect(activityChart).toBeVisible();
  await expect(activityChart.getByText(
    'Monthly watch events · July 2026 is month to date; average uses completed months',
    { exact: true },
  )).toBeVisible();
  await expect(activityChart.getByLabel('Average watch events per completed month')).toHaveText('15.0');
  await expect(activityChart.getByLabel('Average unique films per completed month')).toHaveText('12.0');
  await expect(activityChart.getByText('Watch Events/Mo', { exact: true })).toBeVisible();
  await expect(activityChart.getByText('Unique Films/Mo', { exact: true })).toBeVisible();
  await expect(activityChart.getByRole('img')).toHaveAccessibleName(
    /July 2026 is month to date and is excluded from the completed-month average.*15\.0 watch events and 12\.0 unique films per completed month/,
  );
  await expect(activityChart.getByRole('list', { name: 'Watching Activity data points' })).toContainText(
    'July 2026, month to date: 90 watch events; 70 unique films; average rating 3.9',
  );

  // The chart canvas must stay inside the fixed-height card so the x-axis
  // labels are never painted over by the following section.
  const cardBox = await activityChart.boundingBox();
  const canvasBox = await activityChart.getByRole('img').boundingBox();
  expect(cardBox).not.toBeNull();
  expect(canvasBox).not.toBeNull();
  expect(canvasBox!.y + canvasBox!.height).toBeLessThanOrEqual(cardBox!.y + cardBox!.height + 1);

  // Stat captions must render on a single line, not flex-shrunk into two.
  for (const caption of ['Watch Events/Mo', 'Unique Films/Mo']) {
    const captionBox = await activityChart.getByText(caption, { exact: true }).boundingBox();
    expect(captionBox).not.toBeNull();
    expect(captionBox!.height).toBeLessThanOrEqual(20);
  }
});

test('analysis list panels keep intrinsic heights without animated glass artifacts', async ({ page }) => {
  await page.goto('/analysis');

  const watchesPanel = page.getByRole('heading', { name: 'Recent Watches', exact: true }).locator('..');
  const ratingsPanel = page.getByRole('heading', { name: 'Recent Ratings', exact: true }).locator('..');
  const reviewsPanel = page.getByRole('heading', { name: 'Recent Reviews', exact: true }).locator('..');

  await expect(ratingsPanel).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Coverage Notes', exact: true })).toHaveCount(0);
  for (const panel of [watchesPanel, ratingsPanel, reviewsPanel]) {
    const compositorStyles = await panel.evaluate((element) => {
      const styles = window.getComputedStyle(element);
      return {
        backdropFilter: styles.backdropFilter,
        boxShadow: styles.boxShadow,
        transitionDuration: styles.transitionDuration,
      };
    });
    expect(compositorStyles).toEqual({
      backdropFilter: 'none',
      boxShadow: 'none',
      transitionDuration: '0s',
    });
  }

  if ((page.viewportSize()?.width ?? 0) >= 1280) {
    const [ratingsBox, reviewsBox] = await Promise.all([
      ratingsPanel.boundingBox(),
      reviewsPanel.boundingBox(),
    ]);
    expect(reviewsBox!.height).toBeLessThan(ratingsBox!.height);
  }

  const shimmers = page.getByTestId('stats-card-shimmer');
  expect(await shimmers.count()).toBeGreaterThan(0);
  const shimmerTransformsBefore = await shimmers.evaluateAll((elements) => (
    elements.map((element) => window.getComputedStyle(element).transform)
  ));
  await page.waitForTimeout(300);
  const shimmerTransformsAfter = await shimmers.evaluateAll((elements) => (
    elements.map((element) => window.getComputedStyle(element).transform)
  ));
  expect(shimmerTransformsAfter).toEqual(shimmerTransformsBefore);
});

test('analysis keeps spoiler review prose hidden until an accessible reveal action', async ({ page }) => {
  await page.route(/^http:\/\/(?:127\.0\.0\.1|localhost):8000\/profiles\/[^/]+\/analysis$/, (route) => {
    const username = new URL(route.request().url()).pathname.split('/')[2];
    const reviewText = username === 'bravo'
      ? 'A different spoiler review for bravo.'
      : 'A concise fixture review.';
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...profileAnalysis,
        username,
        recent_reviews: [
          { ...profileAnalysis.recent_reviews[0], review_text: reviewText },
          profileAnalysis.recent_reviews[1],
        ],
      }),
    });
  });
  await page.goto('/analysis');

  const spoilerText = page.getByText('A concise fixture review.', { exact: true });
  const reveal = page.getByRole('button', {
    name: 'Reveal spoiler review for Short Review (2026)',
  });

  await expect(spoilerText).toBeHidden();
  await expect(reveal).toHaveAttribute('aria-expanded', 'false');
  await expect(page.getByText('A second concise fixture review.', { exact: true })).toBeVisible();

  await reveal.click();
  await expect(spoilerText).toBeVisible();
  await expect(page.getByRole('button', {
    name: 'Hide spoiler review for Short Review (2026)',
  })).toHaveAttribute('aria-expanded', 'true');

  await page.getByRole('combobox').selectOption('bravo');
  const nextSpoilerText = page.getByText('A different spoiler review for bravo.', { exact: true });
  await expect(nextSpoilerText).toBeHidden();
  await expect(page.getByRole('button', {
    name: 'Reveal spoiler review for Short Review (2026)',
  })).toHaveAttribute('aria-expanded', 'false');
});

test('analysis shows Coverage Notes only for actionable limitations', async ({ page }) => {
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

  await page.goto('/analysis');

  const coverageNotes = page.getByRole('heading', { name: 'Coverage Notes', exact: true });
  await expect(coverageNotes).toHaveCount(0);

  limitations = [
    'RSS-only data can omit older diary entries.',
    'This partial import does not include the watchlist.',
  ];
  await page.reload();

  await expect(coverageNotes).toBeVisible();
  await expect(page.getByRole('listitem').filter({ hasText: 'RSS-only data can omit older diary entries.' })).toBeVisible();
  await expect(page.getByRole('listitem').filter({ hasText: 'This partial import does not include the watchlist.' })).toBeVisible();
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

test('compare labels a single written review as a spotlight and protects spoiler prose', async ({ page }) => {
  await page.goto('/compare');

  const dossier = page.getByRole('tabpanel', { name: 'Pair Dossier' });
  const spoilerText = dossier.getByText(
    'The identity loop changes how every earlier scene reads.',
    { exact: true },
  );

  await expect(dossier.getByRole('heading', { name: 'Review Spotlight', exact: true })).toBeVisible();
  await expect(dossier.getByRole('heading', { name: 'Review Face-off', exact: true })).toHaveCount(0);
  await expect(dossier.getByText('No written review', { exact: true })).toBeVisible();
  await expect(spoilerText).toBeHidden();

  await dossier.getByRole('button', {
    name: "Reveal spoiler review for alpha's review of Predestination (2014)",
  }).click();
  await expect(spoilerText).toBeVisible();
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
  await expect(page.getByRole('link', { name: 'View film on Letterboxd' })).toHaveAttribute(
    'href',
    'https://letterboxd.com/film/fallback-fixture/',
  );
  await expect(page.getByRole('link', { name: 'View film on TMDB' })).toHaveAttribute(
    'href',
    'https://www.themoviedb.org/movie/550',
  );
  await expect(page.locator('img[src*="missing-poster"]')).toHaveCount(0);
  const brokenImages = await page.locator('main img').evaluateAll((images) => images.filter((image) => {
    const element = image as HTMLImageElement;
    return element.complete && element.naturalWidth === 0;
  }).length);
  expect(brokenImages).toBe(0);
});
