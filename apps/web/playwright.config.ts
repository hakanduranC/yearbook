import { defineConfig, devices } from '@playwright/test'

const live = process.env.E2E_LIVE === '1'
const mockPort = 8089
const apiTarget = live ? 'http://localhost:8080' : `http://localhost:${mockPort}`

export default defineConfig({
  testDir: './tests/e2e',
  globalSetup: './tests/e2e/global-setup.ts',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: 'http://localhost:3000',
    trace: 'retain-on-failure',
    locale: 'de-DE',
  },
  projects: [
    { name: 'iphone-14', use: { ...devices['iPhone 14'] } },
    { name: 'pixel-7', use: { ...devices['Pixel 7'] } },
    // Same iPhone 14 geometry and UA on the Chromium engine, for hosts where WebKit cannot run.
    { name: 'iphone-14-chromium', use: { ...devices['iPhone 14'], browserName: 'chromium' } },
  ],
  webServer: [
    ...(live
      ? []
      : [
          {
            command: `node tests/e2e/mock-api.mjs ${mockPort}`,
            url: `http://localhost:${mockPort}/api/v1/health`,
            reuseExistingServer: true,
            timeout: 15_000,
          },
        ]),
    {
      command: 'pnpm dev',
      url: 'http://localhost:3000/api/health',
      reuseExistingServer: live,
      timeout: 60_000,
      env: {
        API_PROXY_TARGET: apiTarget,
        API_INTERNAL_URL: `${apiTarget}/api/v1`,
        PUBLIC_WEB_ORIGIN: 'http://localhost:3000',
      },
    },
  ],
})
