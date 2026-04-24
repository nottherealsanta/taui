import { test, expect } from './fixtures'

test.describe('Code reference rendering', () => {
  test('renders inline and standalone code refs with preview + modal', async ({ appReady }) => {
    await appReady.locator('.nav-row.heading', { hasText: 'Design System' }).click()

    const codeChip = appReady.locator('.code-ref-chip', { hasText: 'src/lib/sample.ts:renderChip' })
    await expect(codeChip).toBeVisible()

    const standalonePreview = appReady.locator('.code-ref-inline-preview')
    await expect(standalonePreview).toBeVisible()
    await expect(standalonePreview).toContainText('src/lib/standalone.ts:10-24')
    await expect(standalonePreview).toContainText('renderStandalonePreview')

    await standalonePreview.click()
    const modal = appReady.locator('[role="dialog"][aria-label="Code reference file"]')
    await expect(modal).toBeVisible()
    await expect(modal).toContainText('src/lib/standalone.ts')
    await expect(modal).toContainText('10-24')

    await appReady.keyboard.press('Escape')
    await expect(modal).not.toBeVisible()
  })

  test('shows full file content when symbol resolution fails but file exists', async ({ appReady }) => {
    await appReady.locator('.nav-row.heading', { hasText: 'Design System' }).click()
    const codeChip = appReady.locator('.code-ref-chip', { hasText: 'src/lib/missing.ts:missingThing' })
    await expect(codeChip).toBeVisible()

    await codeChip.click()
    const modal = appReady.locator('[role="dialog"][aria-label="Code reference file"]')
    await expect(modal).toBeVisible()
    await expect(modal).toContainText('src/lib/missing.ts')
    // When symbol resolution fails but file can be read, we show the file content as fallback
    await expect(modal).toContainText('Mock File Content')

    await appReady.keyboard.press('Escape')
    await expect(modal).not.toBeVisible()
  })
})
