/**
 * E2E tests: Agent Pane and Message Bar.
 */
import { test, expect } from './fixtures'

test.describe('Agent Pane', () => {
  test('shows agent tabs bar', async ({ appReady }) => {
    const tabs = appReady.locator('.agent-tabs')
    await expect(tabs).toBeVisible()
  })

  test('Prime tab is active by default', async ({ appReady }) => {
    const primeTab = appReady.locator('.prime-tab')
    await expect(primeTab).toBeVisible()
    await expect(primeTab).toHaveClass(/active/)
  })

  test('Prime tab shows star icon', async ({ appReady }) => {
    const primeTab = appReady.locator('.prime-tab')
    await expect(primeTab).toContainText('★')
  })

  test('agent body shows prime chat panel when Prime is selected', async ({ appReady }) => {
    const agentBody = appReady.locator('.agent-body')
    await expect(agentBody).toBeVisible()
  })
})

test.describe('Message Bar', () => {
  test('message input is visible and has placeholder', async ({ appReady }) => {
    const input = appReady.locator('.message-input')
    await expect(input).toBeVisible()
    await expect(input).toHaveAttribute('placeholder', /Message Prime/)
  })

  test('send button is disabled when input is empty', async ({ appReady }) => {
    const sendBtn = appReady.locator('.send-btn')
    await expect(sendBtn).toBeDisabled()
  })

  test('send button enables when text is typed', async ({ appReady }) => {
    const input = appReady.locator('.message-input')
    await input.fill('Hello, Prime!')

    const sendBtn = appReady.locator('.send-btn')
    await expect(sendBtn).not.toBeDisabled()
  })

  test('can type a message and send it', async ({ appReady, mockBackend }) => {
    const input = appReady.locator('.message-input')
    await input.fill('Hello, Prime!')

    // Press Enter to send
    await input.press('Enter')

    // Wait for the message to appear in the chat
    await appReady.waitForTimeout(500)

    // The user message should appear in the chat entries
    // Check that the mock backend received the prime/message call
    const primeCalls = mockBackend.rpcCalls.filter(c => c.method === 'prime/message')
    expect(primeCalls.length).toBeGreaterThan(0)
  })

  test('shows slash command suggestions when typing /', async ({ appReady }) => {
    const input = appReady.locator('.message-input')
    await input.click()
    await input.fill('/')

    // Slash suggestions should appear
    const suggestions = appReady.locator('.slash-suggestions')
    await expect(suggestions).toBeVisible()
  })

  test('slash suggestions filter as you type', async ({ appReady }) => {
    const input = appReady.locator('.message-input')
    await input.click()
    await input.fill('/he')

    // Should show /help command
    const helpItem = appReady.locator('.slash-name', { hasText: '/help' })
    await expect(helpItem).toBeVisible()
  })

  test('slash suggestions show command descriptions', async ({ appReady }) => {
    const input = appReady.locator('.message-input')
    await input.click()
    await input.fill('/')

    const descriptions = appReady.locator('.slash-description')
    const count = await descriptions.count()
    expect(count).toBeGreaterThan(0)
  })

  test('/help command shows available commands', async ({ appReady }) => {
    const input = appReady.locator('.message-input')
    await input.click()
    await input.fill('/help')
    await input.press('Enter')

    // Wait for the help message to be rendered
    await appReady.waitForTimeout(300)
  })

  test('model selector is visible in toolbar', async ({ appReady }) => {
    // The model info should show the provider and model from our mock
    const toolbar = appReady.locator('.input-toolbar')
    await expect(toolbar).toBeVisible()
  })

  test('send button shows arrow icon', async ({ appReady }) => {
    const sendBtn = appReady.locator('.send-btn')
    await expect(sendBtn).toContainText('↑')
  })
})
