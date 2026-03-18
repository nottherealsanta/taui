<!--
  8.7 Toast.svelte
  Renders ephemeral toast notifications from the toasts store.
  Mount once in App.svelte, bottom-right corner.
-->
<script lang="ts">
  import { toasts } from '$stores/toasts.svelte'
</script>

{#if toasts.entries.length > 0}
  <div class="toast-container" aria-live="polite" aria-atomic="false">
    {#each toasts.entries as toast (toast.id)}
      <div class="toast {toast.kind}" role="alert">
        <span class="toast-msg">{toast.message}</span>
        <button
          class="toast-close"
          onclick={() => toasts.dismiss(toast.id)}
          aria-label="Dismiss notification"
        >✕</button>
      </div>
    {/each}
  </div>
{/if}

<style lang="postcss">
  .toast-container {
    position: fixed;
    bottom: 60px;
    right: 16px;
    z-index: 1000;
    display: flex;
    flex-direction: column;
    gap: 8px;
    pointer-events: none;
    max-width: 420px;
  }

  .toast {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    padding: 9px 12px;
    border-radius: 5px;
    font-size: 12px;
    line-height: 1.45;
    pointer-events: all;
    animation: slide-in 0.18s ease;
    border: 1px solid var(--border);
    background-color: var(--bg-surface);
    color: var(--fg-primary);
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.25);
  }

  .toast.info { border-left: 3px solid var(--fg-accent); }
  .toast.warn { border-left: 3px solid var(--status-warning, #f0a500); }
  .toast.error { border-left: 3px solid var(--status-blocked, #f85149); }

  .toast-msg { flex: 1; word-break: break-word; }

  .toast-close {
    background: transparent;
    border: none;
    color: var(--fg-muted);
    cursor: pointer;
    font-size: 10px;
    padding: 1px 3px;
    flex-shrink: 0;
    border-radius: 2px;
    line-height: 1;
    transition: color 0.15s;
  }
  .toast-close:hover { color: var(--fg-primary); }

  @keyframes slide-in {
    from { opacity: 0; transform: translateX(20px); }
    to   { opacity: 1; transform: translateX(0); }
  }
</style>
