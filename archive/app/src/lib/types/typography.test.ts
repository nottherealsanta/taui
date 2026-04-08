/**
 * 9.2 Typography unit tests — ported from ui/tests/typography_tests (implicit).
 */

import { describe, it, expect } from 'vitest'
import {
  INDENT_PER_LEVEL,
  MAX_CONTENT_WIDTH,
  MARKDOWN_TEXT_SIZE,
  MARKDOWN_LINE_HEIGHT,
  depthToHeadingStyle,
  depthToRowStyle,
  indentPx,
  splitRootMarkdown,
} from './typography'

describe('constants', () => {
  it('INDENT_PER_LEVEL is 24', () => {
    expect(INDENT_PER_LEVEL).toBe(24)
  })

  it('MAX_CONTENT_WIDTH is 820', () => {
    expect(MAX_CONTENT_WIDTH).toBe(820)
  })

  it('MARKDOWN_TEXT_SIZE is 16', () => {
    expect(MARKDOWN_TEXT_SIZE).toBe(16)
  })

  it('MARKDOWN_LINE_HEIGHT is 1.45', () => {
    expect(MARKDOWN_LINE_HEIGHT).toBe(1.45)
  })
})

describe('depthToHeadingStyle', () => {
  it('depth 0 is body text weight 400', () => {
    const s = depthToHeadingStyle(0)
    expect(s.fontWeight).toBe(400)
    expect(s.fontSize).toBe(16)
  })

  it('depth 1 is h2 — largest heading (22px 600)', () => {
    const s = depthToHeadingStyle(1)
    expect(s.fontSize).toBe(22)
    expect(s.fontWeight).toBe(600)
  })

  it('depth 2 is sub-heading (18px 500)', () => {
    const s = depthToHeadingStyle(2)
    expect(s.fontSize).toBe(18)
    expect(s.fontWeight).toBe(500)
  })

  it('depth 3+ falls back to body text (16px 400)', () => {
    expect(depthToHeadingStyle(3).fontSize).toBe(16)
    expect(depthToHeadingStyle(3).fontWeight).toBe(400)
    expect(depthToHeadingStyle(10).fontSize).toBe(16)
  })
})

describe('depthToRowStyle', () => {
  it('returns font-size as px string', () => {
    const s = depthToRowStyle(1)
    expect(s.fontSize).toBe('22px')
  })

  it('returns fontWeight as number', () => {
    const s = depthToRowStyle(1)
    expect(typeof s.fontWeight).toBe('number')
    expect(s.fontWeight).toBe(600)
  })
})

describe('indentPx', () => {
  it('depth 0 has no indent', () => {
    expect(indentPx(0)).toBe(0)
  })

  it('depth 1 is INDENT_PER_LEVEL px', () => {
    expect(indentPx(1)).toBe(INDENT_PER_LEVEL)
  })

  it('depth 3 is 3 × INDENT_PER_LEVEL px', () => {
    expect(indentPx(3)).toBe(3 * INDENT_PER_LEVEL)
  })
})

describe('splitRootMarkdown', () => {
  it('extracts title from first non-empty line', () => {
    const [title] = splitRootMarkdown('Hello World\nsome body text')
    expect(title).toBe('Hello World')
  })

  it('strips leading markdown heading markers', () => {
    const [title] = splitRootMarkdown('# My Project\nsome body')
    expect(title).toBe('My Project')
  })

  it('strips ## heading marker', () => {
    const [title] = splitRootMarkdown('## Sub Heading')
    expect(title).toBe('Sub Heading')
  })

  it('returns body text after title line', () => {
    const [, body] = splitRootMarkdown('Title\nLine 2\nLine 3')
    expect(body).toContain('Line 2')
    expect(body).toContain('Line 3')
  })

  it('returns empty body when only a title', () => {
    const [, body] = splitRootMarkdown('Title only')
    expect(body).toBe('')
  })

  it('handles leading blank lines before title', () => {
    const [title] = splitRootMarkdown('\n\n  \nActual Title\nbody')
    expect(title).toBe('Actual Title')
  })

  it('returns empty title for all-blank markdown', () => {
    const [title, body] = splitRootMarkdown('   \n  ')
    expect(title).toBe('')
    expect(body).toBe('')
  })
})
