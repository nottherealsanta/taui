/**
 * Maps incoming server notifications to app state mutations.
 * Called by the connection manager for every notification received.
 */

import type { AgentDetailEvent, AgentType, RunLine } from '$types/index'
import { agentStateFromString } from '$types/index'
import { appState } from '$stores/app-state.svelte'
import type { ServerNotification } from '$services/backend-client'

export function handleNotification(notification: ServerNotification): void {
  const { method, params } = notification
  const p = params as Record<string, unknown>

  switch (method) {
    // ── Spec notifications ───────────────────────────────────────────────
    case 'spec/nodeChanged': {
      if (p['node']) {
        appState.applyNodeChange(p['node'] as Parameters<typeof appState.applyNodeChange>[0])
      }
      break
    }

    // ── Agent notifications ──────────────────────────────────────────────
    case 'agent/stateChanged': {
      const agentId = p['agent_id'] as string
      const rawState = (p['state'] as string) ?? 'idle'
      const specRef = (p['spec_ref'] as string) ?? ''
      const tier = (p['tier'] as 'high' | 'medium' | 'low') ?? 'medium'
      const agentType = (p['agent_type'] as AgentType) ?? 'root'
      const displayName = (p['display_name'] as string) ?? agentId
      appState.upsertAgent({
        agentId,
        specRef,
        state: agentStateFromString(rawState),
        tier,
        agentType,
        displayName,
      })
      break
    }

    case 'agent/lockChanged': {
      const branches = (p['locked_branches'] as string[]) ?? []
      appState.setLockedBranches(branches)
      break
    }

    case 'agent/questionAsked': {
      const agentId = p['agent_id'] as string
      appState.addPendingQuestion({
        agentId,
        questionNodeRef: (p['spec_ref'] as string) ?? '',
        question: (p['question'] as string) ?? '',
        options: (p['options'] as string[]) ?? [],
      })
      break
    }

    case 'agent/questionAnswered': {
      const agentId = p['agent_id'] as string
      appState.removePendingQuestion(agentId)
      break
    }

    case 'agent/toolBrief': {
      const agentId = p['agent_id'] as string
      const brief = (p['brief'] as string) ?? null
      appState.setToolBrief(agentId, brief)
      break
    }

    // ── Agent detail stream (from agent/subscribe) ────────────────────────
    case 'agent/subscribeEvent': {
      const agentId = p['agent_id'] as string
      const event = parseDetailEvent(p['event'] as Record<string, unknown>)
      if (event) {
        // Reflect state changes in the AgentInfo too.
        if (event.type === 'stateChange') {
          appState.setAgentState(agentId, event.state)
        }
        appState.appendDetailEvent(agentId, event)
      }
      break
    }

    // ── Prime streaming notifications ────────────────────────────────────
    case 'prime/token': {
      const text = (p['text'] as string) ?? ''
      appState.appendPrimeStreamToken(text)
      break
    }

    case 'prime/toolCall': {
      appState.addPrimeToolCall({
        callId: (p['call_id'] as string) ?? '',
        toolName: (p['tool_name'] as string) ?? '',
        arguments: p['arguments'] ?? {},
        status: 'running',
      })
      break
    }

    case 'prime/toolResult': {
      appState.completePrimeToolCall({
        callId: (p['call_id'] as string) ?? '',
        output: (p['output'] as string) ?? null,
        error: (p['error'] as string) ?? null,
        durationMs: (p['duration_ms'] as number) ?? null,
      })
      break
    }

    case 'prime/done': {
      appState.finalizePrimeStream()
      break
    }

    case 'prime/minionLaunched': {
      appState.addPrimeMinion({
        minionId: (p['minion_id'] as string) ?? '',
        task: (p['task'] as string) ?? '',
        status: 'running',
        events: [],
      })
      break
    }

    case 'prime/minionDone': {
      appState.completePrimeMinion(
        (p['minion_id'] as string) ?? '',
        (p['result'] as string) ?? null,
      )
      break
    }

    case 'prime/agentLaunched': {
      appState.addPrimeAgentLaunched({
        agentId: (p['agent_id'] as string) ?? '',
        displayName: (p['display_name'] as string) ?? '',
        task: (p['task'] as string) ?? '',
      })
      break
    }

    // ── Run / Terminal notifications ──────────────────────────────────────
    case 'run/output': {
      const runId = p['run_id'] as number
      const stream = ((p['stream'] as string) === 'stderr' ? 'stderr' : 'stdout') as RunLine['stream']
      const text = (p['line'] as string) ?? ''
      // Only accept lines matching the current run.
      if (appState.runState.runId === null || appState.runState.runId === runId) {
        if (appState.runState.runId === null) {
          appState.setRunStatus('running', runId)
        }
        appState.addRunLine({ stream, text })
      }
      break
    }

    case 'run/completed': {
      const exitCode = (p['exit_code'] as number) ?? null
      const rawStatus = (p['status'] as string) ?? 'completed'
      const status = (rawStatus === 'stopped' ? 'stopped' : rawStatus === 'error' ? 'error' : 'completed') as 'completed' | 'stopped' | 'error'
      appState.setRunStatus(status, undefined, undefined, undefined, exitCode)
      break
    }

    default:
      // Unknown notifications are silently ignored.
      break
  }
}

// ─── Detail event parser ─────────────────────────────────────────────────────

function parseDetailEvent(raw: Record<string, unknown> | null | undefined): AgentDetailEvent | null {
  if (!raw) return null
  const type = raw['type'] as string

  switch (type) {
    case 'message':
      return {
        type: 'message',
        role: (raw['role'] as string) ?? 'assistant',
        content: (raw['content'] as string) ?? '',
      }

    case 'tool_call':
      return {
        type: 'toolCall',
        callId: (raw['call_id'] as string) ?? '',
        toolName: (raw['tool_name'] as string) ?? '',
        arguments: raw['arguments'] ?? {},
      }

    case 'tool_result':
      return {
        type: 'toolResult',
        callId: (raw['call_id'] as string) ?? '',
        output: (raw['output'] as string) ?? null,
        error: (raw['error'] as string) ?? null,
        durationMs: (raw['duration_ms'] as number) ?? null,
      }

    case 'token':
      return {
        type: 'token',
        text: (raw['text'] as string) ?? '',
      }

    case 'state_change':
      return {
        type: 'stateChange',
        state: agentStateFromString((raw['state'] as string) ?? 'idle'),
      }

    default:
      return null
  }
}
