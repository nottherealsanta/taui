/**
 * Theme store — auto-detects system preference (prefers-color-scheme),
 * listens for changes, and applies `data-theme` attribute to the document
 * root so CSS variables defined in app.css switch correctly.
 */

type Theme = 'dark' | 'light'

import { backendClient } from '$services/backend-client'

function detectSystemTheme(): Theme {
  if (typeof window === 'undefined') return 'dark'
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

function applyTheme(theme: Theme): void {
  if (typeof document === 'undefined') return
  if (theme === 'light') {
    document.documentElement.setAttribute('data-theme', 'light')
  } else {
    document.documentElement.removeAttribute('data-theme')
  }
}

// ─── Reactive store ────────────────────────────────────────────────────────────

class ThemeStore {
  current: Theme = $state(detectSystemTheme())
  /** Whether the user has made an explicit choice (overriding system theme). */
  userOverride: boolean = false

  constructor() {
    applyTheme(this.current)

    // Listen for system theme changes — only follow if user hasn't overridden
    if (typeof window !== 'undefined') {
      const mql = window.matchMedia('(prefers-color-scheme: light)')
      mql.addEventListener('change', (e) => {
        if (!this.userOverride) {
          this._apply(e.matches ? 'light' : 'dark')
        }
      })
    }
  }

  /** Apply theme without persisting to backend (system-driven or internal use). */
  private _apply(theme: Theme): void {
    this.current = theme
    applyTheme(theme)
  }

  /** Explicitly set theme (user action) — persists to backend. */
  set(theme: Theme): void {
    this.userOverride = true
    this.current = theme
    applyTheme(theme)
    void backendClient.uiSetTheme(theme)
  }

  toggle(): void {
    this.set(this.current === 'dark' ? 'light' : 'dark')
  }

  get isDark(): boolean {
    return this.current === 'dark'
  }

  /**
   * Called on startup from the backend snapshot. Only applies if the snapshot
   * represents an explicit user preference (not null/undefined/"system").
   */
  applySnapshot(theme: Theme): void {
    this.userOverride = true
    this._apply(theme)
  }

  /** Reset back to following the system theme. */
  followSystem(): void {
    this.userOverride = false
    this._apply(detectSystemTheme())
    void backendClient.uiSetTheme('system')
  }
}

export const theme: ThemeStore = import.meta.hot?.data?.theme ?? new ThemeStore()
if (import.meta.hot) {
  import.meta.hot.data.theme = theme
}
export type { Theme }
