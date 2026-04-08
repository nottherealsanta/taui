/**
 * Lightweight toast notification store (Phase 8.7).
 * Components call `toast.info/warn/error(message)` to show ephemeral banners.
 */

export type ToastKind = 'info' | 'warn' | 'error'

export interface ToastEntry {
  id: number
  kind: ToastKind
  message: string
}

class ToastStore {
  entries: ToastEntry[] = $state([])
  private nextId = 1
  private timers = new Map<number, ReturnType<typeof setTimeout>>()

  show(kind: ToastKind, message: string, durationMs = 4000): void {
    const id = this.nextId++
    this.entries = [...this.entries, { id, kind, message }]
    const timer = setTimeout(() => this.dismiss(id), durationMs)
    this.timers.set(id, timer)
  }

  info(message: string, durationMs?: number): void { this.show('info', message, durationMs) }
  warn(message: string, durationMs?: number): void { this.show('warn', message, durationMs) }
  error(message: string, durationMs?: number): void { this.show('error', message, durationMs) }

  dismiss(id: number): void {
    const timer = this.timers.get(id)
    if (timer !== undefined) {
      clearTimeout(timer)
      this.timers.delete(id)
    }
    this.entries = this.entries.filter((e) => e.id !== id)
  }
}

export const toasts: ToastStore = import.meta.hot?.data?.toasts ?? new ToastStore()
if (import.meta.hot) {
  import.meta.hot.data ??= {}
  import.meta.hot.data.toasts = toasts
}
