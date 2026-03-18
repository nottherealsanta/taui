<!--
  4.8 QuestionOverlay.svelte
  Overlay on a node when an agent poses a pending question.
  Renders option buttons + free-text input for custom answers.
-->
<script lang="ts">
  import type { PendingQuestion } from '$types/index'
  import { backendClient } from '$services/backend-client'
  import { appState } from '$stores/app-state.svelte'

  interface Props {
    question: PendingQuestion
  }
  const { question }: Props = $props()

  let customAnswer = $state('')
  let submitting = $state(false)

  async function answer(text: string) {
    if (submitting || !text.trim()) return
    submitting = true
    try {
      await backendClient.agentAnswerQuestion(question.agentId, text.trim())
      appState.removePendingQuestion(question.agentId)
    } catch (e) {
      console.error('[QuestionOverlay] answer failed', e)
    } finally {
      submitting = false
    }
  }

  function handleCustomKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      answer(customAnswer)
    }
    e.stopPropagation()
  }
</script>

<div class="question-overlay" role="dialog" aria-modal="true" aria-label="Agent question">
  <div class="question-header">
    <span class="question-icon">?</span>
    <span class="question-agent">agent asks</span>
  </div>

  <p class="question-text selectable">{question.question}</p>

  {#if question.options.length > 0}
    <div class="options">
      {#each question.options as opt}
        <button
          class="option-btn"
          disabled={submitting}
          onclick={() => answer(opt)}
        >{opt}</button>
      {/each}
    </div>
  {/if}

  <div class="custom-row">
    <input
      class="custom-input selectable"
      type="text"
      placeholder="Custom answer…"
      bind:value={customAnswer}
      disabled={submitting}
      onkeydown={handleCustomKeydown}
      autocomplete="off"
    />
    <button
      class="submit-btn"
      disabled={!customAnswer.trim() || submitting}
      onclick={() => answer(customAnswer)}
    >{submitting ? '…' : '↑'}</button>
  </div>
</div>

<style lang="postcss">
  .question-overlay {
    margin: 4px 8px 8px;
    padding: 10px 12px;
    background-color: var(--bg-elevated);
    border: 1px solid var(--status-warning);
    border-radius: 6px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    font-size: 12px;
  }

  .question-header {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .question-icon {
    width: 18px;
    height: 18px;
    border-radius: 50%;
    background-color: var(--status-warning);
    color: #000;
    font-weight: 700;
    font-size: 11px;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }

  .question-agent {
    font-size: 10px;
    font-weight: 600;
    color: var(--status-warning);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .question-text {
    margin: 0;
    color: var(--fg-primary);
    line-height: 1.5;
  }

  .options {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .option-btn {
    padding: 4px 12px;
    background: var(--element-bg);
    border: 1px solid var(--border);
    border-radius: 4px;
    color: var(--fg-primary);
    font-size: 12px;
    cursor: pointer;
    transition: all 0.15s;
  }
  .option-btn:hover:not(:disabled) {
    background-color: var(--element-hover);
    border-color: var(--fg-accent);
    color: var(--fg-accent);
  }
  .option-btn:disabled { opacity: 0.5; cursor: not-allowed; }

  .custom-row {
    display: flex;
    gap: 6px;
  }

  .custom-input {
    flex: 1;
    background: var(--element-bg);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 12px;
    font-family: var(--font-sans);
    color: var(--fg-primary);
    outline: none;
    transition: border-color 0.15s;
  }
  .custom-input:focus { border-color: var(--fg-accent); }
  .custom-input:disabled { opacity: 0.5; }
  .custom-input::placeholder { color: var(--fg-muted); }

  .submit-btn {
    width: 28px;
    height: 28px;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: transparent;
    color: var(--fg-muted);
    font-size: 14px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.15s;
    flex-shrink: 0;
  }
  .submit-btn:hover:not(:disabled) {
    background-color: var(--fg-accent);
    color: var(--bg-base);
    border-color: var(--fg-accent);
  }
  .submit-btn:disabled { opacity: 0.3; cursor: not-allowed; }
</style>
