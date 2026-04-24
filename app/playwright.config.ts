import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  // Must be 1 — all tests share the same dedicated mock backend port.
  workers: 1,
  reporter: 'html',

  use: {
    baseURL: 'http://127.0.0.1:1421',
    trace: 'on-first-retry',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  webServer: {
    command: 'VITE_TAUI_BACKEND_WS=ws://127.0.0.1:8010/ws npm run dev -- --host 127.0.0.1 --port 1421',
    url: 'http://127.0.0.1:1421',
    reuseExistingServer: false,
    timeout: 30_000,
  },
})
