/**
 * Playwright test fixtures for Taui E2E tests.
 *
 * Provides a `mockBackend` fixture that starts a mock WebSocket server
 * once per worker and shares it across all tests in that worker.
 * The frontend connects to ws://127.0.0.1:8010/ws in Playwright.
 */
import { test as base, expect, type Page } from '@playwright/test'
import { MockBackend } from './mock-backend'

type TauiWorkerFixtures = {
  mockBackend: MockBackend
}

type TauiFixtures = {
  /** Navigate and wait for the app to be fully connected. */
  appReady: Page
}

export const test = base.extend<TauiFixtures, TauiWorkerFixtures>({
  mockBackend: [async ({}, use) => {
    const backend = new MockBackend({ port: 8010 })
    await backend.start()
    await use(backend)
    await backend.stop()
  }, { scope: 'worker' }],

  appReady: async ({ page, mockBackend }, use) => {
    // Clear recorded RPC calls from previous tests
    mockBackend.rpcCalls.length = 0
    // Navigate to the app — the Vite dev server is already running (from playwright.config.ts)
    await page.goto('/')
    // Wait for connection to establish and the app to become "ready"
    // The connection-screen disappears and the main layout shows up
    await page.waitForSelector('.tangle-nav-sidebar', { timeout: 15_000 })
    // Wait for Svelte to flush derived state so sidebar content is actually rendered
    // (the sidebar element appears when connectionState='ready', but navItems may not
    // be rendered yet in that same microtask)
    await page.waitForFunction(
      () =>
        document.querySelector('.tangle-nav-sidebar .empty-state') === null,
      { timeout: 10_000 },
    )
    await use(page)
  },
})

export { expect }
