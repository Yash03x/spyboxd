import { defineConfig, devices } from '@playwright/test';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const isCI = Boolean(process.env.CI);
const localBaseUrl = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000';
const baseURL = isCI ? 'http://localhost:3100' : localBaseUrl;
const testClerkKey = 'Y2xlcmsuZXhhbXBsZS50ZXN0JA==';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: isCI,
  retries: isCI ? 2 : 0,
  workers: isCI ? 2 : undefined,
  timeout: 30_000,
  expect: { timeout: 8_000 },
  reporter: isCI ? 'github' : 'list',
  outputDir: join(tmpdir(), 'spyboxd-playwright-results'),
  use: {
    baseURL,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    video: 'retain-on-failure',
  },
  webServer: {
    command: isCI
      ? 'npm run build && npm run start -- --hostname localhost --port 3100'
      : 'npm run dev -- --hostname localhost --port 3000',
    url: baseURL,
    reuseExistingServer: !isCI,
    timeout: 120_000,
    env: {
      ...process.env,
      NEXT_PUBLIC_API_BASE_URL: 'http://127.0.0.1:8000',
      ...(isCI ? {
        NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY: `pk_live_${testClerkKey}`,
        CLERK_SECRET_KEY: `sk_live_${testClerkKey}`,
      } : {}),
    },
  },
  projects: [
    {
      name: 'desktop-chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'mobile-chromium',
      use: { ...devices['Pixel 7'] },
    },
  ],
});
