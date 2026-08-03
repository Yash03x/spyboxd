import { expect, test } from '@playwright/test';

import { SECTIONS } from '../src/components/terminal/sections';
import { installApiMocks } from './fixtures/api';

/**
 * Every tab publishes a panel count beside its label. Three of them were
 * transcribed from the design handoff and then drifted as panels were added or
 * cut: One person advertised 20 against 24 on screen, Two people 10 against 11,
 * Profiles 7 against 5. Nobody noticed, because nothing counted.
 *
 * The whole argument of this product is that a number on screen is true, so a
 * navigation badge is not allowed to be a rough estimate either. This walks
 * every tab and holds the badge to what the page actually renders.
 */
test.beforeEach(async ({ page }) => {
  // Non-admin: Data › Profiles renders an extra request-queue panel for admins,
  // and the badge is what every reader gets rather than what one of them does.
  await installApiMocks(page, { isAdmin: false });
});

for (const section of SECTIONS) {
  for (const tab of section.tabs) {
    test(`${section.name} › ${tab.label} renders the ${tab.panels} panels it advertises`, async ({
      page,
    }) => {
      await page.goto(`/${section.id}?tab=${tab.id}`);

      const panels = page.locator('.terminal-root section');
      // Panels stream in as their queries settle, so wait for the count rather
      // than sampling it the instant navigation resolves.
      await expect(panels).toHaveCount(tab.panels);
    });
  }
}

test('the tab row prints the same number the section definition holds', async ({ page }) => {
  await page.goto('/people?tab=one');

  for (const tab of SECTIONS.find((entry) => entry.id === 'people')!.tabs) {
    // Addressed by href rather than by accessible name: the badge renders as
    // label and count run together ("ONE PERSON24"), and the name computation
    // inserts a separator that the visible text does not have.
    const link = page.locator(`a[href="/people?tab=${tab.id}"]`).first();
    await expect(link).toHaveText(`${tab.label}${tab.panels}`);
  }
});
