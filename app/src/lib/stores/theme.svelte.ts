/**
 * Theme store — dark / light toggle, persisted in localStorage.
 * Applies `data-theme` attribute to the document root so CSS variables
 * defined in app.css switch correctly.
 */

type Theme = 'dark' | 'light'

const STORAGE_KEY = 'taui-theme'

function readStored(): Theme {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    if (v === 'light' || v === 'dark') return v
  } catch {
    // SSR / restricted environment
  }
  return 'dark'
}

function applyTheme(theme: Theme): void {
  if (typeof document === 'undefined') return
  if (theme === 'light') {
    document.documentElement.setAttribute('data-theme', 'light')
  } else {
    document.documentElement.removeAttribute('data-theme')
  }
  try {
    localStorage.setItem(STORAGE_KEY, theme)
  } catch {
    // ignore
  }
}

// ─── Reactive store ────────────────────────────────────────────────────────────

class ThemeStore {
  current: Theme = $state(readStored())

  constructor() {
    // Apply immediately (before first render) to avoid flash.
    applyTheme(this.current)
  }

  toggle(): void {
    this.set(this.current === 'dark' ? 'light' : 'dark')
  }

  set(theme: Theme): void {
    this.current = theme
    applyTheme(theme)
  }

  get isDark(): boolean {
    return this.current === 'dark'
  }
}

export const theme: ThemeStore = import.meta.hot?.data?.theme ?? new ThemeStore()
if (import.meta.hot) {
  import.meta.hot.data.theme = theme
}
export type { Theme }
