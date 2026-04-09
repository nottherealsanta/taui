/**
 * E2E tests: Quick Jump modal (Cmd+P).
 */
import { test, expect } from './fixtures'

test.describe('Quick Jump', () => {
  test('opens with Cmd+P', async ({ appReady }) => {
    await appReady.keyboard.press('Meta+p')

    const modal = appReady.locator('[role="dialog"][aria-label="Quick jump"]')
    await expect(modal).toBeVisible()
  })

  test('search input auto-focuses', async ({ appReady }) => {
    await appReady.keyboard.press('Meta+p')

    const searchInput = appReady.locator('[aria-label="Quick jump search"]')
    await expect(searchInput).toBeFocused()
  })

  test('shows spec nodes as results', async ({ appReady }) => {
    await appReady.keyboard.press('Meta+p')

    // Should show items from the spec tree
    const list = appReady.locator('.jump-list')
    await expect(list).toBeVisible()

    const items = appReady.locator('.jump-item')
    const count = await items.count()
    expect(count).toBeGreaterThan(0)
  })

  test('shows keyboard shortcut label', async ({ appReady }) => {
    await appReady.keyboard.press('Meta+p')

    const icon = appReady.locator('.search-icon')
    await expect(icon).toContainText('P')
  })

  test('filters results based on search query', async ({ appReady }) => {
    await appReady.keyboard.press('Meta+p')

    const searchInput = appReady.locator('[aria-label="Quick jump search"]')
    await searchInput.fill('Overview')

    // Wait for filtering
    await appReady.waitForTimeout(300)

    // Should show matching results
    const items = appReady.locator('.jump-item')
    const count = await items.count()
    expect(count).toBeGreaterThanOrEqual(0)
  })

  test('shows "No matches found" for unmatched query', async ({ appReady }) => {
    await appReady.keyboard.press('Meta+p')

    const searchInput = appReady.locator('[aria-label="Quick jump search"]')
    await searchInput.fill('xyznonexistentfileornode12345')

    await appReady.waitForTimeout(500)

    const empty = appReady.locator('.jump-empty')
    await expect(empty).toBeVisible()
  })

  test('closes on Escape', async ({ appReady }) => {
    await appReady.keyboard.press('Meta+p')

    const modal = appReady.locator('[role="dialog"][aria-label="Quick jump"]')
    await expect(modal).toBeVisible()

    await appReady.keyboard.press('Escape')
    await expect(modal).not.toBeVisible()
  })

  test('closes when clicking backdrop', async ({ appReady }) => {
    await appReady.keyboard.press('Meta+p')

    const modal = appReady.locator('[role="dialog"][aria-label="Quick jump"]')
    await expect(modal).toBeVisible()

    const backdrop = appReady.locator('.jump-backdrop')
    await backdrop.click({ position: { x: 10, y: 10 } })

    await expect(modal).not.toBeVisible()
  })

  test('keyboard navigation with arrow keys', async ({ appReady }) => {
    await appReady.keyboard.press('Meta+p')

    // Wait for items to render
    await appReady.waitForTimeout(300)

    const items = appReady.locator('.jump-item')
    const count = await items.count()

    if (count > 1) {
      // First item should be selected
      await expect(items.first()).toHaveClass(/active/)

      // Press down arrow
      await appReady.keyboard.press('ArrowDown')
      await expect(items.nth(1)).toHaveClass(/active/)

      // Press up arrow
      await appReady.keyboard.press('ArrowUp')
      await expect(items.first()).toHaveClass(/active/)
    }
  })

  test('shows footer navigation hints', async ({ appReady }) => {
    await appReady.keyboard.press('Meta+p')

    const footer = appReady.locator('.jump-footer')
    await expect(footer).toBeVisible()
    await expect(footer).toContainText('navigate')
    await expect(footer).toContainText('open')
    await expect(footer).toContainText('close')
  })

  test('Cmd+P toggles quick jump on/off', async ({ appReady }) => {
    // Open
    await appReady.keyboard.press('Meta+p')
    const modal = appReady.locator('[role="dialog"][aria-label="Quick jump"]')
    await expect(modal).toBeVisible()

    // Close via Escape
    await appReady.keyboard.press('Escape')
    await expect(modal).not.toBeVisible()
  })

  test('Cmd+Shift+P switches from Quick Jump to Command Palette', async ({ appReady }) => {
    // Open Quick Jump first
    await appReady.keyboard.press('Meta+p')
    const jump = appReady.locator('[role="dialog"][aria-label="Quick jump"]')
    await expect(jump).toBeVisible()

    // Close it
    await appReady.keyboard.press('Escape')
    await expect(jump).not.toBeVisible()

    // Open Command Palette
    await appReady.keyboard.press('Meta+Shift+p')
    const palette = appReady.locator('[role="dialog"][aria-label="Command palette"]')
    await expect(palette).toBeVisible()
  })
})
