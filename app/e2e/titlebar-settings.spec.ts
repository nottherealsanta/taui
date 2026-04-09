/**
 * E2E tests: Title bar and Settings modal.
 */
import { test, expect } from './fixtures'

test.describe('Title Bar', () => {
  test('shows project title in the center', async ({ appReady }) => {
    const title = appReady.locator('.titlebar-title')
    await expect(title).toHaveText('Test Project')
  })

  test('has a settings button', async ({ appReady }) => {
    const settingsBtn = appReady.locator('.settings-btn')
    await expect(settingsBtn).toBeVisible()
  })

  test('clicking settings button opens settings modal', async ({ appReady }) => {
    const settingsBtn = appReady.locator('.settings-btn')
    await settingsBtn.click()

    const modal = appReady.locator('[role="dialog"][aria-label="Settings"]')
    await expect(modal).toBeVisible()

    // Settings title
    const heading = appReady.locator('.settings-title')
    await expect(heading).toHaveText('Settings')
  })
})

test.describe('Settings Modal', () => {
  test('shows theme information', async ({ appReady }) => {
    // Open settings
    await appReady.locator('.settings-btn').click()

    const modal = appReady.locator('[role="dialog"][aria-label="Settings"]')
    await expect(modal).toBeVisible()

    // Theme setting row should be present
    const themeLabel = modal.locator('.setting-label', { hasText: 'Theme' })
    await expect(themeLabel).toBeVisible()
  })

  test('shows prompts editor', async ({ appReady }) => {
    await appReady.locator('.settings-btn').click()

    const modal = appReady.locator('[role="dialog"][aria-label="Settings"]')

    // Prompts label
    const promptsLabel = modal.locator('.setting-label', { hasText: 'Prompts' })
    await expect(promptsLabel).toBeVisible()

    // Prompt selector dropdown
    const select = modal.locator('select')
    await expect(select).toBeVisible()

    // Prompt editor textarea
    const textarea = modal.locator('.prompt-editor')
    await expect(textarea).toBeVisible()
  })

  test('can switch between prompt types', async ({ appReady }) => {
    await appReady.locator('.settings-btn').click()

    const modal = appReady.locator('[role="dialog"][aria-label="Settings"]')
    const select = modal.locator('select')

    // Switch to root_agent_system
    await select.selectOption('root_agent_system')
    await expect(select).toHaveValue('root_agent_system')
  })

  test('Save and Reset buttons are present', async ({ appReady }) => {
    await appReady.locator('.settings-btn').click()

    const modal = appReady.locator('[role="dialog"][aria-label="Settings"]')

    const saveBtn = modal.locator('.action-btn', { hasText: 'Save' })
    await expect(saveBtn).toBeVisible()

    const resetBtn = modal.locator('.action-btn', { hasText: 'Reset' })
    await expect(resetBtn).toBeVisible()
  })

  test('closes when clicking close button', async ({ appReady }) => {
    await appReady.locator('.settings-btn').click()

    const modal = appReady.locator('[role="dialog"][aria-label="Settings"]')
    await expect(modal).toBeVisible()

    // Click close button
    const closeBtn = modal.locator('[aria-label="Close settings"]')
    await closeBtn.click()

    await expect(modal).not.toBeVisible()
  })

  test('closes when pressing Escape', async ({ appReady }) => {
    await appReady.locator('.settings-btn').click()

    const modal = appReady.locator('[role="dialog"][aria-label="Settings"]')
    await expect(modal).toBeVisible()

    await appReady.keyboard.press('Escape')

    await expect(modal).not.toBeVisible()
  })

  test('closes when clicking backdrop', async ({ appReady }) => {
    await appReady.locator('.settings-btn').click()

    const modal = appReady.locator('[role="dialog"][aria-label="Settings"]')
    await expect(modal).toBeVisible()

    // Click the backdrop (outside the modal)
    const backdrop = appReady.locator('.settings-backdrop')
    await backdrop.click({ position: { x: 10, y: 10 } })

    await expect(modal).not.toBeVisible()
  })
})
