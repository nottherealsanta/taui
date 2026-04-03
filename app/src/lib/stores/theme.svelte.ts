/**
 * Theme store — auto-detects system preference (prefers-color-scheme),
 * listens for changes, and applies `data-theme` attribute to the document
 * root so CSS variables defined in app.css switch correctly.
 */

type Theme = 'dark' | 'light'

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

  constructor() {
    applyTheme(this.current)

    // Listen for system theme changes
    if (typeof window !== 'undefined') {
      const mql = window.matchMedia('(prefers-color-scheme: light)')
      mql.addEventListener('change', (e) => {
        this.set(e.matches ? 'light' : 'dark')
      })
    }
  }

  set(theme: Theme): void {
    this.current = theme
    applyTheme(theme)
  }

  toggle(): void {
    this.set(this.current === 'dark' ? 'light' : 'dark')
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
