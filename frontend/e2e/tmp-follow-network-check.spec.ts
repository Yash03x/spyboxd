import { expect, test, type Page } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

// TEMPORARY verification spec for the interactive follow network. Delete after use.

const OUT = '/private/tmp/claude-501/-Users-yash-code-letterboxd-reviewer/262be126-72b7-4b9e-bb4e-39ee851542c2/scratchpad';

const GROUP = ['alpha', 'bravo', 'charlie', 'delta', 'echo', 'foxtrot'];

const PAIRS = [
  { a: 'alpha', b: 'bravo', a_follows_b: true, b_follows_a: true, mutual: true },
  { a: 'alpha', b: 'charlie', a_follows_b: true, b_follows_a: false, mutual: false },
  { a: 'alpha', b: 'delta', a_follows_b: false, b_follows_a: true, mutual: false },
  { a: 'bravo', b: 'echo', a_follows_b: true, b_follows_a: true, mutual: true },
  { a: 'charlie', b: 'foxtrot', a_follows_b: true, b_follows_a: true, mutual: true },
  { a: 'delta', b: 'echo', a_follows_b: true, b_follows_a: false, mutual: false },
];

const ROLLUPS = Object.fromEntries(
  GROUP.map((username) => [username, { follows_in_group: 2, followed_by_in_group: 1 }]),
);

async function installGraphMocks(page: Page) {
  await page.route(/\/api\/follow-graph\/mutuals/, (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ profiles: GROUP, pairs: PAIRS, rollups: ROLLUPS }),
  }));

  await page.route(/\/api\/profiles\/[^/]+\/follow-graph/, (route) => {
    const username = decodeURIComponent(new URL(route.request().url()).pathname.split('/')[3]);
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        username,
        following_count: 3,
        followers_count: 3,
        total: 2,
        edges: [
          {
            direction: 'following',
            counterpart_username: `${username}_outsider`,
            counterpart_display_name: null,
            counterpart_avatar_url: null,
            counterpart_profile_url: null,
            position: 1,
            is_imported_profile: false,
            counterpart_profile_id: null,
            removed_at: null,
          },
          {
            direction: 'follower',
            counterpart_username: `${username}_fan`,
            counterpart_display_name: null,
            counterpart_avatar_url: null,
            counterpart_profile_url: null,
            position: 2,
            is_imported_profile: false,
            counterpart_profile_id: null,
            removed_at: null,
          },
        ],
      }),
    });
  });
}

test('follow network ego view walk', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(`pageerror: ${error.message}`));
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(`console: ${message.text()}`);
  });

  await installApiMocks(page);
  await installGraphMocks(page);

  await page.goto('/network');
  const network = page.getByTestId('follow-network');
  await expect(network).toBeVisible();
  await expect(page.getByText('6 profiles · 3 mutual · 3 one-way')).toBeVisible();
  await page.waitForTimeout(600);
  await network.screenshot({ path: `${OUT}/full-view.png` });

  // 1. Click a node -> ego view.
  await page.getByRole('button', { name: 'Centre the network on @alpha' }).click();
  await expect(page.getByRole('button', { name: 'Back to full network' })).toBeVisible();
  await expect(page.getByRole('button', { name: "Open @alpha's deep dive analysis" })).toBeVisible();
  await page.waitForTimeout(900);
  await network.screenshot({ path: `${OUT}/ego-alpha.png` });

  // Untracked leaves render but are not buttons.
  await expect(network.getByText('alpha_outsider', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: /alpha_outsider/ })).toHaveCount(0);

  // 4. Click a tracked leaf -> re-centre.
  await page.getByRole('button', { name: 'Centre the network on @bravo' }).click();
  await expect(page.getByRole('button', { name: "Open @bravo's deep dive analysis" })).toBeVisible();
  await page.waitForTimeout(900);
  await network.screenshot({ path: `${OUT}/ego-bravo.png` });

  // 5. Escape returns to the full network and restores focus to that node.
  await page.keyboard.press('Escape');
  await expect(page.getByRole('button', { name: 'Back to full network' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Centre the network on @bravo' })).toBeFocused();
  await page.waitForTimeout(900);
  await network.screenshot({ path: `${OUT}/back-to-full.png` });

  // 2. Back control also returns to the full network.
  await page.getByRole('button', { name: 'Centre the network on @charlie' }).click();
  await expect(page.getByRole('button', { name: 'Back to full network' })).toBeVisible();
  await page.getByRole('button', { name: 'Back to full network' }).click();
  await expect(page.getByRole('button', { name: 'Back to full network' })).toHaveCount(0);

  // 3. Centre node opens the deep dive for that profile.
  await page.getByRole('button', { name: 'Centre the network on @echo' }).click();
  await page.getByRole('button', { name: "Open @echo's deep dive analysis" }).click();
  await expect(page).toHaveURL(/\/analysis\?profile=echo/);
  await expect(page.locator('select.input-field')).toHaveValue('echo');
  await expect(page.getByRole('heading', { name: /Rating Distribution for @echo/ })).toBeVisible();
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${OUT}/analysis-deeplink.png` });

  expect(errors, errors.join('\n')).toEqual([]);
});

test('analysis honours ?profile= and keeps the selector working', async ({ page }) => {
  await installApiMocks(page);
  await page.goto('/analysis?profile=echo');
  const selector = page.locator('select.input-field');
  await expect(selector).toHaveValue('echo');
  await expect(page.getByRole('heading', { name: /Rating Distribution for @echo/ })).toBeVisible();

  await selector.selectOption('golf');
  await expect(selector).toHaveValue('golf');
  await expect(page).toHaveURL(/\/analysis\?profile=golf/);
  await expect(page.getByRole('heading', { name: /Rating Distribution for @golf/ })).toBeVisible();

  // A case-insensitive deep link still resolves.
  await page.goto('/analysis?profile=INDIA');
  await expect(selector).toHaveValue('india');

  // No param keeps the legacy default (first profile in scope).
  await page.goto('/analysis');
  await expect(selector).toHaveValue('alpha');
});

test('keyboard reaches the ego view', async ({ page }) => {
  await installApiMocks(page);
  await installGraphMocks(page);
  await page.goto('/network');
  await expect(page.getByTestId('follow-network')).toBeVisible();

  const node = page.getByRole('button', { name: 'Centre the network on @alpha' });
  await node.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('button', { name: "Open @alpha's deep dive analysis" })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(node).toBeFocused();
});
