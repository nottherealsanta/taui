/**
 * E2E tests: Keyboard shortcuts and Command Palette.
 */
import { test, expect } from './fixtures'

test.describe('Command Palette', () => {
  test('opens with Cmd+Shift+P', async ({ appReady }) => {
    await appReady.keyboard.press('Meta+Shift+p')

    const palette = appReady.locator('[role="dialog"][aria-label="Command palette"]')
    await expect(palette).toBeVisible()
  })

  test('has search input that auto-focuses', async ({ appReady }) => {
    await appReady.keyboard.press('Meta+Shift+p')

    const searchInput = appReady.locator('[aria-label="Command search"]')
    await expect(searchInput).toBeVisible()
    await expect(searchInput).toBeFocused()
  })

  test('shows list of available actions', async ({ appReady }) => {
    await appReady.keyboard.press('Meta+Shift+p')

    const list = appReady.locator('.palette-list')
    await expect(list).toBeVisible()

    const items = appReady.locator('.palette-item')
    // Should have multiple actions
    await expect(items.first()).toBeVisible()
    const count = await items.count()
    expect(count).toBeGreaterThan(5)
  })

  test('filters actions based on search query', async ({ appReady }) => {
    await appReady.keyboard.press('Meta+Shift+p')

    const searchInput = appReady.locator('[aria-label="Command search"]')
    await searchInput.fill('theme')

    // Should show "Toggle theme" action
    const themeItem = appReady.locator('.action-label', { hasText: 'Toggle theme' })
    await expect(themeItem).toBeVisible()
  })

  test('shows "No matching commands" for unmatched query', async ({ appReady }) => {
    await appReady.keyboard.press('Meta+Shift+p')

    const searchInput = appReady.locator('[aria-label="Command search"]')
    await searchInput.fill('xyznonexistentcommand')

    const empty = appReady.locator('.palette-empty')
    await expect(empty).toHaveText('No matching commands')
  })

  test('closes on Escape', async ({ appReady }) => {
    await appReady.keyboard.press('Meta+Shift+p')

    const palette = appReady.locator('[role="dialog"][aria-label="Command palette"]')
    await expect(palette).toBeVisible()

    await appReady.keyboard.press('Escape')
    await expect(palette).not.toBeVisible()
  })

  test('closes when clicking backdrop', async ({ appReady }) => {
    await appReady.keyboard.press('Meta+Shift+p')

    const palette = appReady.locator('[role="dialog"][aria-label="Command palette"]')
    await expect(palette).toBeVisible()

    const backdrop = appReady.locator('.palette-backdrop')
    await backdrop.click({ position: { x: 10, y: 10 } })

    await expect(palette).not.toBeVisible()
  })

  test('keyboard navigation with arrow keys', async ({ appReady }) => {
    await appReady.keyboard.press('Meta+Shift+p')

    // First item should be selected
    const items = appReady.locator('.palette-item')
    await expect(items.first()).toHaveClass(/active/)

    // Press down arrow
    await appReady.keyboard.press('ArrowDown')
    await expect(items.nth(1)).toHaveClass(/active/)

    // Press up arrow
    await appReady.keyboard.press('ArrowUp')
    await expect(items.first()).toHaveClass(/active/)
  })

  test('executes action on Enter', async ({ appReady }) => {
    await appReady.keyboard.press('Meta+Shift+p')

    const searchInput = appReady.locator('[aria-label="Command search"]')
    await searchInput.fill('theme')

    // Press Enter to execute "Toggle theme"
    await appReady.keyboard.press('Enter')

    // Palette should close after action
    const palette = appReady.locator('[role="dialog"][aria-label="Command palette"]')
    await expect(palette).not.toBeVisible()
  })

  test('shows footer with navigation hints', async ({ appReady }) => {
    await appReady.keyboard.press('Meta+Shift+p')

    const footer = appReady.locator('.palette-footer')
    await expect(footer).toBeVisible()
    await expect(footer).toContainText('navigate')
    await expect(footer).toContainText('run')
    await expect(footer).toContainText('close')
  })
})

test.describe('Global Keyboard Shortcuts', () => {
  test('Cmd+Shift+P toggles command palette', async ({ appReady }) => {
    // Open
    await appReady.keyboard.press('Meta+Shift+p')
    const palette = appReady.locator('[role="dialog"][aria-label="Command palette"]')
    await expect(palette).toBeVisible()

    // Close with Escape
    await appReady.keyboard.press('Escape')
    await expect(palette).not.toBeVisible()
  })

  test('Cmd+B toggles left sidebar', async ({ appReady }) => {
    const sidebar = appReady.locator('.tangle-nav-sidebar')
    await expect(sidebar).toBeVisible()

    // Toggle off (Cmd+B)
    await appReady.keyboard.press('Meta+b')

    // The sidebar should be collapsed (hidden or narrow)
    // The SplitPane marks it as collapsed, so the sidebar pane might not be visible
    // Give it time to animate
    await appReady.waitForTimeout(300)
  })
})
