import { expect, test } from '@playwright/test';

import { installApiMocks } from './fixtures/api';

/**
 * The frontend states which build it is, the way the API states its revision
 * at /health. In this environment the value is the 'dev' fallback; production
 * bundles carry the git SHA, and the deploy canary holds it to the API's.
 */
test('every page carries the build revision on its body', async ({ page }) => {
  await installApiMocks(page);

  await page.goto('/overview');

  await expect(page.locator('body')).toHaveAttribute('data-build-revision', /^(dev|[0-9a-f]{40})$/);
});
