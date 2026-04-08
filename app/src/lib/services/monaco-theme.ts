/**
 * Monaco Editor theme definitions for Taui.
 * Ported from ui/src/theme/ (dark / light token values).
 *
 * Registers two themes:
 *   - "taui-dark"  (default)
 *   - "taui-light"
 *
 * Call registerMonacoThemes() once before creating any Monaco editor instance.
 */

// ─── Color palette references ─────────────────────────────────────────────────
// These are the resolved hex values from ThemeColors and StatusColors in Rust.
// Keeping them here (not CSS vars) because Monaco's theme API is imperative and
// does not participate in CSS custom property resolution.

const DARK = {
  bg:       '#151515',
  surface:  '#000000',
  elevated: '#0b0b0b',
  border:   '#2d3749',
  fgPrimary:'#ededed',
  fgMuted:  '#9fb0c2',
  fgAccent: '#7cc7ff',
  elementBg:'#1d2532',
  selection: '#2d3f59',
  lineHighlight: '#1d2532',
  // Syntax
  keyword:  '#ff7b72',
  string:   '#a5d6ff',
  number:   '#79c0ff',
  comment:  '#6a737d',
  type:     '#ffa657',
  func:     '#d2a8ff',
  variable: '#e6edf3',
  property: '#79c0ff',
  operator: '#ff7b72',
  constant: '#79c0ff',
  tag:      '#7ee787',
  attribute:'#ffa657',
  invalid:  '#ff6b6b',
} as const

const LIGHT = {
  bg:       '#ffffff',
  surface:  '#ededed',
  elevated: '#f6f6f6',
  border:   '#d8e1ee',
  fgPrimary:'#1a2433',
  fgMuted:  '#5e7288',
  fgAccent: '#0d6bcf',
  elementBg:'#f0f4fa',
  selection: '#d9e7fb',
  lineHighlight: '#f0f4fa',
  // Syntax
  keyword:  '#cf222e',
  string:   '#0550ae',
  number:   '#0550ae',
  comment:  '#6e7781',
  type:     '#953800',
  func:     '#8250df',
  variable: '#1a2433',
  property: '#0550ae',
  operator: '#cf222e',
  constant: '#0550ae',
  tag:      '#116329',
  attribute:'#953800',
  invalid:  '#c53030',
} as const

// ─── Theme builder ────────────────────────────────────────────────────────────

type MonacoThemeName = 'taui-dark' | 'taui-light'

type ColorPalette = {
  bg: string; surface: string; elevated: string; border: string
  fgPrimary: string; fgMuted: string; fgAccent: string
  elementBg: string; selection: string; lineHighlight: string
  keyword: string; string: string; number: string; comment: string
  type: string; func: string; variable: string; property: string
  operator: string; constant: string; tag: string; attribute: string
  invalid: string
}

interface TokenRule {
  token: string
  foreground?: string
  fontStyle?: string
}

function makeThemeData(c: ColorPalette): {
  base: 'vs-dark' | 'vs'
  inherit: boolean
  rules: TokenRule[]
  colors: Record<string, string>
} {
  const isDark = c === DARK

  return {
    base: isDark ? 'vs-dark' : 'vs',
    inherit: false,
    rules: [
      // Keywords
      { token: 'keyword',         foreground: c.keyword },
      { token: 'keyword.control', foreground: c.keyword, fontStyle: 'bold' },
      { token: 'storage.type',    foreground: c.keyword },
      { token: 'storage.modifier',foreground: c.keyword },

      // Strings
      { token: 'string',          foreground: c.string },
      { token: 'string.escape',   foreground: c.string },
      { token: 'string.template', foreground: c.string },
      { token: 'string.quoted',   foreground: c.string },

      // Numbers & booleans
      { token: 'number',          foreground: c.number },
      { token: 'constant.numeric',foreground: c.number },
      { token: 'constant.language',foreground: c.number },

      // Comments
      { token: 'comment',         foreground: c.comment, fontStyle: 'italic' },
      { token: 'comment.block',   foreground: c.comment, fontStyle: 'italic' },
      { token: 'comment.line',    foreground: c.comment, fontStyle: 'italic' },

      // Types / classes
      { token: 'entity.name.type',  foreground: c.type },
      { token: 'entity.name.class', foreground: c.type },
      { token: 'entity.name.struct',foreground: c.type },
      { token: 'entity.name.enum',  foreground: c.type },
      { token: 'entity.name.trait', foreground: c.type },
      { token: 'support.type',      foreground: c.type },
      { token: 'support.class',     foreground: c.type },
      { token: 'type',              foreground: c.type },

      // Functions
      { token: 'entity.name.function', foreground: c.func },
      { token: 'support.function',     foreground: c.func },

      // Variables & parameters
      { token: 'variable',           foreground: c.variable },
      { token: 'variable.other',     foreground: c.variable },
      { token: 'variable.parameter', foreground: c.fgMuted },

      // Properties
      { token: 'variable.other.property', foreground: c.property },
      { token: 'support.variable',        foreground: c.property },

      // Operators & punctuation
      { token: 'keyword.operator',  foreground: c.operator },
      { token: 'punctuation',       foreground: c.fgMuted },

      // Constants / enums
      { token: 'constant',          foreground: c.constant },
      { token: 'variable.constant', foreground: c.constant },

      // HTML/XML tags & attributes
      { token: 'entity.name.tag',     foreground: c.tag },
      { token: 'entity.other.attribute-name', foreground: c.attribute },
      { token: 'meta.tag',            foreground: c.fgMuted },

      // Markdown-specific
      { token: 'markup.heading',       foreground: c.keyword, fontStyle: 'bold' },
      { token: 'markup.bold',          foreground: c.fgPrimary, fontStyle: 'bold' },
      { token: 'markup.italic',        foreground: c.fgPrimary, fontStyle: 'italic' },
      { token: 'markup.inline.raw',    foreground: c.string },
      { token: 'markup.fenced_code',   foreground: c.string },
      { token: 'markup.list',          foreground: c.fgAccent },
      { token: 'punctuation.definition.list', foreground: c.fgAccent },

      // Invalid
      { token: 'invalid', foreground: c.invalid },
    ],
    colors: {
      // Editor chrome
      'editor.background':           c.bg,
      'editor.foreground':           c.fgPrimary,
      'editor.lineHighlightBackground': c.lineHighlight,
      'editor.selectionBackground':  c.selection,
      'editor.inactiveSelectionBackground': c.elementBg,
      'editorCursor.foreground':     c.fgAccent,

      // Gutter
      'editorLineNumber.foreground':       c.fgMuted,
      'editorLineNumber.activeForeground': c.fgPrimary,

      // Find / highlight
      'editor.findMatchBackground':          c.selection,
      'editor.findMatchHighlightBackground': c.elementBg,

      // Whitespace & indent guides
      'editorWhitespace.foreground':       c.border,
      'editorIndentGuide.background1':     c.border,
      'editorIndentGuide.activeBackground1': c.fgMuted,

      // Widget / suggest
      'editorWidget.background':     c.elevated,
      'editorWidget.border':         c.border,
      'editorSuggestWidget.background': c.elevated,
      'editorSuggestWidget.border':  c.border,
      'editorSuggestWidget.selectedBackground': c.selection,

      // Minimap
      'minimap.background':          c.bg,
      'minimap.selectionHighlight':  c.selection,

      // Scrollbar
      'scrollbarSlider.background':        isDark ? '#2d374966' : '#00000022',
      'scrollbarSlider.hoverBackground':   isDark ? '#2d3749cc' : '#00000044',
      'scrollbarSlider.activeBackground':  c.fgMuted,

      // Diff editor
      'diffEditor.insertedTextBackground': isDark ? '#2ea04326' : '#2f855a26',
      'diffEditor.removedTextBackground':  isDark ? '#ff6b6b26' : '#c5303026',
    },
  }
}

// ─── Registration ─────────────────────────────────────────────────────────────

let registered = false

/**
 * Register Taui's dark and light Monaco themes.
 * Safe to call multiple times — subsequent calls are no-ops.
 *
 * @param monaco - The monaco-editor module (import('monaco-editor'))
 */
export function registerMonacoThemes(monaco: typeof import('monaco-editor')): void {
  if (registered) return
  registered = true

  monaco.editor.defineTheme('taui-dark', makeThemeData(DARK))
  monaco.editor.defineTheme('taui-light', makeThemeData(LIGHT))
}

/**
 * Returns the Monaco theme name matching the current Taui theme.
 */
export function monacoThemeName(isDark: boolean): MonacoThemeName {
  return isDark ? 'taui-dark' : 'taui-light'
}
