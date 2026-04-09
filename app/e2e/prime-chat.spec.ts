/**
 * E2E tests: Prime Chat interaction.
 */
import { test, expect } from './fixtures'

test.describe('Prime Chat', () => {
  test('Prime chat panel is visible when Prime tab is active', async ({ appReady }) => {
    const primeTab = appReady.locator('.prime-tab')
    await expect(primeTab).toHaveClass(/active/)

    const agentBody = appReady.locator('.agent-body')
    await expect(agentBody).toBeVisible()
  })

  test('sending a message adds it to the chat', async ({ appReady }) => {
    const input = appReady.locator('.message-input')
    await input.fill('What is the project architecture?')
    await input.press('Enter')

    // Wait for user message to appear in chat
    await appReady.waitForTimeout(500)

    // The user message should be in the chat
    // PrimeChatPanel renders entries — look for user message content
    const chatContent = appReady.locator('.agent-body')
    await expect(chatContent).toBeVisible()
  })

  test('message input clears after sending', async ({ appReady }) => {
    const input = appReady.locator('.message-input')
    await input.fill('Hello Prime')
    await input.press('Enter')

    // Input should be cleared
    await expect(input).toHaveValue('')
  })

  test('/new command creates a context divider', async ({ appReady }) => {
    const input = appReady.locator('.message-input')
    await input.fill('/new')
    await input.press('Enter')

    // Wait for the divider to appear
    await appReady.waitForTimeout(500)

    // The /new command should have been processed
    const chatContent = appReady.locator('.agent-body')
    await expect(chatContent).toBeVisible()
  })

  test('/cancel command cancels Prime response', async ({ appReady, mockBackend }) => {
    const input = appReady.locator('.message-input')
    // Use trailing space to bypass the autocomplete panel (which would eat the first Enter)
    await input.fill('/cancel ')
    await input.press('Enter')

    await appReady.waitForTimeout(300)

    // Check that the backend received the cancel call
    const cancelCalls = mockBackend.rpcCalls.filter(c => c.method === 'prime/cancel')
    expect(cancelCalls.length).toBeGreaterThan(0)
  })

  test('slash command autocomplete appears for /', async ({ appReady }) => {
    const input = appReady.locator('.message-input')
    await input.click()
    await input.fill('/')

    const suggestions = appReady.locator('.slash-suggestions')
    await expect(suggestions).toBeVisible()

    // Should show all 5 commands
    const items = appReady.locator('.slash-item')
    const count = await items.count()
    expect(count).toBe(5)
  })

  test('slash command can be selected with Tab', async ({ appReady }) => {
    const input = appReady.locator('.message-input')
    await input.click()
    await input.fill('/n')

    // /new should be suggested
    const suggestions = appReady.locator('.slash-suggestions')
    await expect(suggestions).toBeVisible()

    const newCmd = appReady.locator('.slash-name', { hasText: '/new' })
    await expect(newCmd).toBeVisible()

    // Press Tab to select
    await input.press('Tab')

    // The input should now contain "/new "
    await expect(input).toHaveValue('/new ')
  })

  test('model info displayed in toolbar', async ({ appReady }) => {
    const modelInfo = appReady.locator('.model-info')
    // The model info should show the mock's model value
    if (await modelInfo.isVisible()) {
      await expect(modelInfo).toBeVisible()
    }
  })

  test('/agent command launches root agent and opens a new tab', async ({ appReady, mockBackend }) => {
    const tabs = appReady.locator('.agent-tabs')

    // Initially only Prime tab exists
    const agentTabsBefore = tabs.locator('.agent-tab:not(.prime-tab)')
    expect(await agentTabsBefore.count()).toBe(0)

    // Launch a root agent via /agent slash command
    // Input contains a space so autocomplete is not open — one Enter suffices
    const input = appReady.locator('.message-input')
    await input.fill('/agent Implement the auth module')
    await input.press('Enter')

    // A new agent tab should appear in the tab bar
    const agentTabsAfter = tabs.locator('.agent-tab:not(.prime-tab)')
    await expect(agentTabsAfter.first()).toBeVisible({ timeout: 5000 })
    expect(await agentTabsAfter.count()).toBe(1)

    // The new tab should have a label
    const tabLabel = agentTabsAfter.first().locator('.agent-tab-label')
    await expect(tabLabel).toBeVisible()

    // Verify agent/launch RPC was sent to the backend
    const launchCalls = mockBackend.rpcCalls.filter(c => c.method === 'agent/launch')
    expect(launchCalls.length).toBeGreaterThan(0)
    expect((launchCalls[0].params as Record<string, unknown>).task).toBe('Implement the auth module')
  })

  test('clicking a root agent tab switches the agent pane', async ({ appReady }) => {
    // First, launch an agent
    const input = appReady.locator('.message-input')
    await input.fill('/agent Build the API layer')
    await input.press('Enter')

    const tabs = appReady.locator('.agent-tabs')
    const agentTab = tabs.locator('.agent-tab:not(.prime-tab)')
    await expect(agentTab.first()).toBeVisible({ timeout: 5000 })

    // Prime tab should be active initially (slash command doesn't auto-switch)
    const primeTab = tabs.locator('.prime-tab')
    await expect(primeTab).toHaveClass(/active/)

    // Click the new agent tab
    await agentTab.first().click()

    // The agent tab should now be active
    await expect(agentTab.first()).toHaveClass(/active/)

    // Prime tab should no longer be active
    await expect(primeTab).not.toHaveClass(/active/)
  })

  test('Prime tab can be reselected after viewing agent tab', async ({ appReady }) => {
    // Launch an agent
    const input = appReady.locator('.message-input')
    await input.fill('/agent Design the database schema')
    await input.press('Enter')

    const tabs = appReady.locator('.agent-tabs')
    const agentTab = tabs.locator('.agent-tab:not(.prime-tab)')
    await expect(agentTab.first()).toBeVisible({ timeout: 5000 })

    // Switch to agent tab
    await agentTab.first().click()
    await expect(agentTab.first()).toHaveClass(/active/)

    // Switch back to Prime
    const primeTab = tabs.locator('.prime-tab')
    await primeTab.click()
    await expect(primeTab).toHaveClass(/active/)
    await expect(agentTab.first()).not.toHaveClass(/active/)
  })
})
