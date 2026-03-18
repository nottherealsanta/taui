/**
 * 9.4 Notifications handler tests.
 * Verifies that handleNotification() routes each server notification method
 * to the correct appState mutation.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { handleNotification } from './notifications'
import { appState } from '$stores/app-state.svelte'
import { resetAppState, loadDemoState } from '$stores/app-state.svelte'

beforeEach(() => {
  loadDemoState()
})

// ── spec/nodeChanged ──────────────────────────────────────────────────────────

describe('spec/nodeChanged', () => {
  it('calls appState.applyNodeChange with the node payload', () => {
    const spy = vi.spyOn(appState, 'applyNodeChange')
    const node = { spec_ref: 'specs/_main.md', depth: 0, markdown: '# Updated Root\n\nbody' }

    handleNotification({ method: 'spec/nodeChanged', params: { node } })

    expect(spy).toHaveBeenCalledWith(node)
  })

  it('does nothing when params.node is absent', () => {
    const spy = vi.spyOn(appState, 'applyNodeChange')
    handleNotification({ method: 'spec/nodeChanged', params: {} })
    expect(spy).not.toHaveBeenCalled()
  })
})

// ── agent/stateChanged ────────────────────────────────────────────────────────

describe('agent/stateChanged', () => {
  it('calls appState.upsertAgent with mapped fields', () => {
    const spy = vi.spyOn(appState, 'upsertAgent')

    handleNotification({
      method: 'agent/stateChanged',
      params: {
        agent_id: 'agent-1',
        state: 'running',
        spec_ref: 'specs/ui.md',
        tier: 'senior',
      },
    })

    expect(spy).toHaveBeenCalledOnce()
    const call = spy.mock.calls[0][0]
    expect(call.agentId).toBe('agent-1')
    expect(call.specRef).toBe('specs/ui.md')
    expect(call.tier).toBe('senior')
    // state is mapped through agentStateFromString
    expect(call.state).toBeTruthy()
  })

  it('defaults tier to mid when absent', () => {
    const spy = vi.spyOn(appState, 'upsertAgent')
    handleNotification({
      method: 'agent/stateChanged',
      params: { agent_id: 'agent-2', state: 'idle' },
    })
    expect(spy.mock.calls[0][0].tier).toBe('mid')
  })
})

// ── agent/lockChanged ─────────────────────────────────────────────────────────

describe('agent/lockChanged', () => {
  it('calls appState.setLockedBranches with the branches array', () => {
    const spy = vi.spyOn(appState, 'setLockedBranches')
    handleNotification({
      method: 'agent/lockChanged',
      params: { locked_branches: ['specs/ui.md', 'specs/_main.md'] },
    })
    expect(spy).toHaveBeenCalledWith(['specs/ui.md', 'specs/_main.md'])
  })

  it('passes empty array when locked_branches is absent', () => {
    const spy = vi.spyOn(appState, 'setLockedBranches')
    handleNotification({ method: 'agent/lockChanged', params: {} })
    expect(spy).toHaveBeenCalledWith([])
  })
})

// ── agent/questionAsked ───────────────────────────────────────────────────────

describe('agent/questionAsked', () => {
  it('calls appState.addPendingQuestion with mapped fields', () => {
    const spy = vi.spyOn(appState, 'addPendingQuestion')
    handleNotification({
      method: 'agent/questionAsked',
      params: {
        agent_id: 'agent-3',
        spec_ref: 'specs/chat.md',
        question: 'Which approach?',
        options: ['A', 'B'],
      },
    })
    expect(spy).toHaveBeenCalledOnce()
    const call = spy.mock.calls[0][0]
    expect(call.agentId).toBe('agent-3')
    expect(call.question).toBe('Which approach?')
    expect(call.options).toEqual(['A', 'B'])
  })
})

// ── agent/questionAnswered ────────────────────────────────────────────────────

describe('agent/questionAnswered', () => {
  it('calls appState.removePendingQuestion with agentId', () => {
    const spy = vi.spyOn(appState, 'removePendingQuestion')
    handleNotification({
      method: 'agent/questionAnswered',
      params: { agent_id: 'agent-3' },
    })
    expect(spy).toHaveBeenCalledWith('agent-3')
  })
})

// ── run/output ────────────────────────────────────────────────────────────────

describe('run/output', () => {
  it('adds a run line for stdout', () => {
    // Ensure runState has the right runId (or null to auto-assign)
    appState.setRunStatus('running', 42)

    const spy = vi.spyOn(appState, 'addRunLine')
    handleNotification({
      method: 'run/output',
      params: { run_id: 42, stream: 'stdout', line: 'hello world' },
    })

    expect(spy).toHaveBeenCalledWith({ stream: 'stdout', text: 'hello world' })
  })

  it('adds a run line for stderr', () => {
    appState.setRunStatus('running', 42)
    const spy = vi.spyOn(appState, 'addRunLine')

    handleNotification({
      method: 'run/output',
      params: { run_id: 42, stream: 'stderr', line: 'error text' },
    })

    expect(spy).toHaveBeenCalledWith({ stream: 'stderr', text: 'error text' })
  })

  it('ignores output for a different run_id', () => {
    appState.setRunStatus('running', 10)
    const spy = vi.spyOn(appState, 'addRunLine')

    handleNotification({
      method: 'run/output',
      params: { run_id: 99, stream: 'stdout', line: 'stale' },
    })

    expect(spy).not.toHaveBeenCalled()
  })
})

// ── run/completed ─────────────────────────────────────────────────────────────

describe('run/completed', () => {
  it('calls appState.setRunStatus with completed status and exit code', () => {
    const spy = vi.spyOn(appState, 'setRunStatus')
    handleNotification({
      method: 'run/completed',
      params: { exit_code: 0, status: 'completed' },
    })
    expect(spy).toHaveBeenCalled()
    const [status, , , , exitCode] = spy.mock.calls[0]
    expect(status).toBe('completed')
    expect(exitCode).toBe(0)
  })

  it('maps status=stopped correctly', () => {
    const spy = vi.spyOn(appState, 'setRunStatus')
    handleNotification({
      method: 'run/completed',
      params: { exit_code: null, status: 'stopped' },
    })
    const [status] = spy.mock.calls[0]
    expect(status).toBe('stopped')
  })

  it('maps status=error correctly', () => {
    const spy = vi.spyOn(appState, 'setRunStatus')
    handleNotification({
      method: 'run/completed',
      params: { exit_code: 1, status: 'error' },
    })
    const [status] = spy.mock.calls[0]
    expect(status).toBe('error')
  })
})

// ── unknown method ────────────────────────────────────────────────────────────

describe('unknown notifications', () => {
  it('ignores notifications with unrecognized methods', () => {
    // Should not throw
    expect(() =>
      handleNotification({ method: 'some/futureMethod', params: { data: 42 } })
    ).not.toThrow()
  })
})
