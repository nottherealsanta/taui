import { Editor, type EditorOptions } from '@tiptap/core';
import Document from '@tiptap/extension-document';
import Paragraph from '@tiptap/extension-paragraph';
import Text from '@tiptap/extension-text';
import Bold from '@tiptap/extension-bold';
import Italic from '@tiptap/extension-italic';
import Code from '@tiptap/extension-code';
import CodeBlock from '@tiptap/extension-code-block';
import HardBreak from '@tiptap/extension-hard-break';
import History from '@tiptap/extension-history';
import Placeholder from '@tiptap/extension-placeholder';
import Heading from '@tiptap/extension-heading';
import BulletList from '@tiptap/extension-bullet-list';
import OrderedList from '@tiptap/extension-ordered-list';
import ListItem from '@tiptap/extension-list-item';
import Blockquote from '@tiptap/extension-blockquote';
import HorizontalRule from '@tiptap/extension-horizontal-rule';
import { Markdown } from 'tiptap-markdown';
import { RpcClient } from './rpc';

export interface NodeEditorState {
  specRef: string;
  title: string;
  depth: number;
  content: string;
  dirty: boolean;
  saving: boolean;
  error: string | null;
  lastSavedAt: number | null;
  debounceTimer: number | null;
  editorInstance: Editor | null;
  blurHandler: (() => void) | null;
  pendingSave: boolean;
  needsNormalizationSave: boolean;
}

export interface PerNodeEditorManager {
  // Lifecycle
  mount(specRef: string, container: HTMLElement): Promise<void>;
  unmount(specRef: string): void;
  unmountAll(): void;
  
  // State getters
  getState(specRef: string): NodeEditorState | undefined;
  isDirty(specRef: string): boolean;
  isSaving(specRef: string): boolean;
  getError(specRef: string): string | null;
  hasUnsavedChanges(): boolean;
  
  // Save operations
  save(specRef: string): Promise<boolean>;
  saveAll(): Promise<void>;
  flush(specRef: string): Promise<boolean>;
  
  // Reconciliation
  remapSpecRef(oldSpecRef: string, newSpecRef: string): void;
  getUnsavedContent(): Map<string, string>;
  restoreContent(savedContent: Map<string, string>): void;
}

const AUTOSAVE_DELAY = 800; // ms
const LEGACY_ESCAPED_HTML_RE = /&lt;\s*\/?\s*([a-z][\w-]*)\b/i;
const LEGACY_RAW_HTML_RE = /<\s*\/?\s*(p|ul|ol|li|h[1-6]|code|pre|blockquote|hr|br)\b/i;
let autoRepairedCount = 0;

// Development mode flag - can be made configurable
const IS_DEV = typeof process !== 'undefined' && process.env?.NODE_ENV === 'development';

/**
 * Decodes HTML entities in a string (e.g., &lt;p&gt; -> <p>)
 */
function decodeHtmlEntities(text: string): string {
  const textarea = document.createElement('textarea');
  textarea.innerHTML = text;
  return textarea.value;
}

function decodeHtmlEntitiesRepeatedly(text: string, maxPasses: number = 3): string {
  let current = text;
  for (let i = 0; i < maxPasses; i += 1) {
    const decoded = decodeHtmlEntities(current);
    if (decoded === current) {
      return current;
    }
    current = decoded;
  }
  return current;
}

function normalizeWhitespace(value: string): string {
  return value.trim().replace(/\s+/g, ' ').toLowerCase();
}

function looksLikeLegacyEscapedHtml(content: string): boolean {
  return LEGACY_ESCAPED_HTML_RE.test(content) && content.includes('&gt;');
}

function looksLikeLegacyRawHtml(content: string): boolean {
  return LEGACY_RAW_HTML_RE.test(content) && content.includes('>');
}

function htmlToMarkdownLike(html: string): string {
  return html
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<li[^>]*>/gi, '- ')
    .replace(/<\/li>/gi, '\n')
    .replace(/<\/(p|h[1-6]|blockquote|pre|ul|ol)>/gi, '\n\n')
    .replace(/<hr[^>]*>/gi, '\n\n---\n\n')
    .replace(/<[^>]+>/g, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

function normalizeTitleAndCarry(rawTitle: string): { title: string; carryContent: string; repaired: boolean } {
  if (!rawTitle) {
    return { title: 'Untitled', carryContent: '', repaired: false };
  }

  let title = rawTitle;
  let repaired = false;

  if (title.includes('&')) {
    const decoded = decodeHtmlEntitiesRepeatedly(title);
    if (decoded !== title) {
      title = decoded;
      repaired = true;
    }
  }

  if (looksLikeLegacyEscapedHtml(title)) {
    title = decodeHtmlEntitiesRepeatedly(title);
    repaired = true;
  }

  if (looksLikeLegacyRawHtml(title)) {
    const markdownLike = htmlToMarkdownLike(title);
    const lines = markdownLike.split('\n');
    let firstNonEmpty = -1;
    for (let i = 0; i < lines.length; i += 1) {
      if (lines[i].trim()) {
        firstNonEmpty = i;
        break;
      }
    }
    if (firstNonEmpty >= 0) {
      const parsedTitle = lines[firstNonEmpty].trim();
      const carryContent = lines
        .slice(firstNonEmpty + 1)
        .join('\n')
        .trim();
      return {
        title: parsedTitle || 'Untitled',
        carryContent,
        repaired: true,
      };
    }
    return { title: 'Untitled', carryContent: '', repaired: true };
  }

  return { title: title.trim() || 'Untitled', carryContent: '', repaired };
}

function stripLeadingDuplicateTitle(content: string, title: string): { content: string; repaired: boolean } {
  if (!content.trim()) {
    return { content: '', repaired: false };
  }

  const lines = content.split('\n');
  let first = 0;
  while (first < lines.length && !lines[first].trim()) {
    first += 1;
  }
  if (first >= lines.length) {
    return { content: '', repaired: false };
  }

  const headingMatch = lines[first].trim().match(/^#{1,6}\s+(.*)$/);
  const firstText = headingMatch ? headingMatch[1] : lines[first];
  if (normalizeWhitespace(firstText) !== normalizeWhitespace(title)) {
    return { content: content.trim(), repaired: false };
  }

  const remaining = lines.slice(first + 1);
  while (remaining.length > 0 && !remaining[0].trim()) {
    remaining.shift();
  }
  return {
    content: remaining.join('\n').trim(),
    repaired: true,
  };
}

function normalizeNodeContent(raw: string): { normalized: string; repaired: boolean } {
  if (!raw) {
    return { normalized: raw, repaired: false };
  }

  let content = raw;
  let repaired = false;

  // Legacy content can be escaped more than once. Decode until stable first.
  if (content.includes('&')) {
    const decoded = decodeHtmlEntitiesRepeatedly(content);
    if (decoded !== content) {
      content = decoded;
      repaired = true;
    }
  }

  // Handle payloads that still contain escaped tags after one pass.
  if (looksLikeLegacyEscapedHtml(content)) {
    content = decodeHtmlEntitiesRepeatedly(content);
    repaired = true;
  }

  // Convert legacy HTML blocks into plain markdown-like text before mounting the editor.
  if (looksLikeLegacyRawHtml(content)) {
    content = htmlToMarkdownLike(content);
    repaired = true;
  }

  return { normalized: content, repaired };
}

/**
 * Validates that all node configurations in the extension list are editable.
 * This guard ensures we maintain the always-editable node policy.
 */
function validateEditableExtensions(extensions: EditorOptions['extensions']): void {
  if (!extensions) return;
  
  for (const ext of extensions) {
    if (!ext) continue;
    
    // Check if this is a node extension with a custom NodeView
    const extConfig = ext as { 
      config?: { 
        addNodeView?: () => { dom: HTMLElement; contentDOM?: HTMLElement } | HTMLElement 
      } 
    };
    
    if (extConfig.config?.addNodeView) {
      try {
        const nodeView = extConfig.config.addNodeView();
        const dom = nodeView instanceof HTMLElement ? nodeView : nodeView.dom;
        
        // Check if contentEditable is set to false
        if (dom && dom.contentEditable === 'false') {
          const errorMsg = `Non-editable custom node detected: ${(ext as { name?: string }).name || 'unknown'}. ` +
            `All custom nodes must be editable (contentEditable !== false). ` +
            `This violates the always-editable node policy.`;
          
          if (IS_DEV) {
            throw new Error(errorMsg);
          } else {
            console.error('[Tiptap Editor Guard]', errorMsg);
          }
        }
      } catch (e) {
        // Only throw in dev mode
        if (IS_DEV && e instanceof Error) {
          throw e;
        }
      }
    }
  }
}

/**
 * Creates the default Tiptap extensions for the editor.
 * This includes basic document/text/paragraph/formatting plus headings and lists for markdown support.
 */
function createDefaultExtensions(): EditorOptions['extensions'] {
  return [
    Document,
    Paragraph,
    Text,
    Bold,
    Italic,
    Code,
    CodeBlock.configure({
      HTMLAttributes: {
        class: 'code-block',
      },
    }),
    HardBreak,
    History,
    Placeholder.configure({
      placeholder: 'Type something...',
    }),
    Heading.configure({
      levels: [1, 2, 3, 4, 5, 6],
    }),
    BulletList,
    OrderedList,
    ListItem,
    Blockquote,
    HorizontalRule,
    Markdown.configure({
      html: false,
      tightLists: true,
      tightListClass: 'tight',
      bulletListMarker: '-',
      linkify: false,
      breaks: false,
      transformPastedText: true,
      transformCopiedText: true,
    }),
  ];
}

export function createPerNodeEditorManager(
  rpc: RpcClient | undefined
): PerNodeEditorManager {
  const editors = new Map<string, NodeEditorState>();
  let saveInProgress = new Set<string>();

  function createInitialState(specRef: string, content: string): NodeEditorState {
    return {
      specRef,
      title: '',
      depth: 1,
      content,
      dirty: false,
      saving: false,
      error: null,
      lastSavedAt: null,
      debounceTimer: null,
      editorInstance: null,
      blurHandler: null,
      pendingSave: false,
      needsNormalizationSave: false,
    };
  }

  function headingPrefixForDepth(depth: number): string {
    const level = Math.max(1, Math.min(6, depth || 1));
    return '#'.repeat(level);
  }

  function composeEditorDocument(title: string, content: string, depth: number): string {
    const normalizedTitle = title.trim() || 'Untitled';
    const heading = `${headingPrefixForDepth(depth)} ${normalizedTitle}`;
    const body = content.trim();
    return body ? `${heading}\n\n${body}` : heading;
  }

  function parseEditorDocument(markdown: string, fallbackTitle: string): { title: string; content: string } {
    const lines = markdown.replace(/\r\n/g, '\n').split('\n');
    let titleIndex = -1;
    for (let i = 0; i < lines.length; i += 1) {
      if (lines[i].trim()) {
        titleIndex = i;
        break;
      }
    }

    if (titleIndex === -1) {
      return { title: fallbackTitle.trim() || 'Untitled', content: '' };
    }

    const firstLine = lines[titleIndex].trim();
    const headingMatch = firstLine.match(/^#{1,6}\s+(.*)$/);
    const parsedTitle = (headingMatch ? headingMatch[1] : firstLine).trim();
    const title = parsedTitle || fallbackTitle.trim() || 'Untitled';

    const bodyLines = lines.slice(titleIndex + 1);
    while (bodyLines.length > 0 && !bodyLines[0].trim()) {
      bodyLines.shift();
    }

    return {
      title,
      content: bodyLines.join('\n').trim(),
    };
  }

  async function loadNodeContent(specRef: string): Promise<{ title: string; content: string; depth: number }> {
    if (!rpc) {
      return { title: '', content: '', depth: 1 };
    }
    try {
      const result = await rpc.request('spec/getNode', { spec_ref: specRef });
      return {
        title: typeof result.node?.title === 'string' ? result.node.title : '',
        content: typeof result.node?.content === 'string' ? result.node.content : '',
        depth: typeof result.node?.depth === 'number' ? result.node.depth : 1,
      };
    } catch (error) {
      console.error(`Failed to load content for ${specRef}:`, error);
      return { title: '', content: '', depth: 1 };
    }
  }

  async function performSave(state: NodeEditorState): Promise<boolean> {
    if (
      !rpc ||
      !state.editorInstance ||
      saveInProgress.has(state.specRef) ||
      (!state.dirty && !state.needsNormalizationSave)
    ) {
      return false;
    }

    saveInProgress.add(state.specRef);
    state.saving = true;
    state.error = null;

    try {
      const markdown = state.editorInstance.storage.markdown.getMarkdown();
      const parsed = parseEditorDocument(markdown, state.title);
      await rpc.request('spec/updateNode', {
        spec_ref: state.specRef,
        patch: {
          title: parsed.title,
          content: parsed.content,
        },
      });
      
      state.title = parsed.title;
      state.content = parsed.content;
      state.dirty = false;
      state.needsNormalizationSave = false;
      state.error = null;
      state.lastSavedAt = Date.now();
      return true;
    } catch (error) {
      console.error(`Failed to save ${state.specRef}:`, error);
      state.error = 'Failed to save. Will retry on next edit.';
      return false;
    } finally {
      state.saving = false;
      saveInProgress.delete(state.specRef);
    }
  }

  function scheduleAutosave(state: NodeEditorState): void {
    // Clear existing timer
    if (state.debounceTimer !== null) {
      window.clearTimeout(state.debounceTimer);
      state.debounceTimer = null;
    }

    // Schedule new autosave
    state.debounceTimer = window.setTimeout(() => {
      state.debounceTimer = null;
      if (state.dirty && !state.saving) {
        void performSave(state);
      }
    }, AUTOSAVE_DELAY);
  }

  async function mount(specRef: string, container: HTMLElement): Promise<void> {
    // Check if already mounted
    const existing = editors.get(specRef);
    if (existing?.editorInstance) {
      // Already mounted, just ensure container is correct
      return;
    }

    // Load content
    const loaded = await loadNodeContent(specRef);

    // Create or update state
    let state: NodeEditorState;
    if (existing) {
      state = existing;
      state.title = loaded.title;
      state.depth = loaded.depth;
      state.content = loaded.content;
    } else {
      state = createInitialState(specRef, loaded.content);
      state.title = loaded.title;
      state.depth = loaded.depth;
      editors.set(specRef, state);
    }

    // Clear container
    container.replaceChildren();

    // Create extensions and validate editable policy
    const extensions = createDefaultExtensions();
    validateEditableExtensions(extensions);

    const normalizedTitle = normalizeTitleAndCarry(loaded.title);
    let normalizedBody = normalizeNodeContent(loaded.content);

    let mergedContent = normalizedBody.normalized;
    if (normalizedTitle.carryContent) {
      mergedContent = mergedContent
        ? `${normalizedTitle.carryContent}\n\n${mergedContent}`
        : normalizedTitle.carryContent;
      normalizedBody = { normalized: mergedContent, repaired: true };
    }

    const stripped = stripLeadingDuplicateTitle(normalizedBody.normalized, normalizedTitle.title);
    state.title = normalizedTitle.title;
    state.content = stripped.content;
    state.needsNormalizationSave =
      normalizedTitle.repaired || normalizedBody.repaired || stripped.repaired;

    if (state.needsNormalizationSave) {
      autoRepairedCount += 1;
      console.info(
        `[Tiptap] Auto-repaired legacy node content for ${specRef}. Total repaired: ${autoRepairedCount}`
      );
    }

    // Create Tiptap editor instance. Start empty and set normalized markdown on create.
    state.editorInstance = new Editor({
      element: container,
      extensions,
      content: '',
      editable: true,
      autofocus: false,
      onUpdate: () => {
        if (!state.dirty) {
          state.dirty = true;
        }
        scheduleAutosave(state);
      },
      onCreate: ({ editor }) => {
        const editorDocument = composeEditorDocument(state.title, state.content, state.depth);
        editor.commands.setContent(editorDocument, false, { preserveWhitespace: 'full' });
      },
      onBlur: () => {
        // Blur handler will be set up separately for immediate save
      },
    });

    // Set up blur handler for immediate save
    state.blurHandler = async () => {
      // Clear any pending autosave
      if (state.debounceTimer !== null) {
        window.clearTimeout(state.debounceTimer);
        state.debounceTimer = null;
      }
      if ((state.dirty || state.needsNormalizationSave) && !state.saving) {
        await performSave(state);
      }
    };

    // Attach blur handler to the editor's DOM element
    const editorEl = state.editorInstance.view.dom as HTMLElement;
    if (editorEl) {
      editorEl.addEventListener('blur', state.blurHandler, true);
    }
  }

  function unmount(specRef: string): void {
    const state = editors.get(specRef);
    if (!state) return;

    // Flush any pending save
    if (state.debounceTimer !== null) {
      window.clearTimeout(state.debounceTimer);
      state.debounceTimer = null;
    }

    // Clean up blur handler
    if (state.blurHandler && state.editorInstance) {
      const editorEl = state.editorInstance.view.dom as HTMLElement;
      if (editorEl) {
        editorEl.removeEventListener('blur', state.blurHandler, true);
      }
      state.blurHandler = null;
    }

    // Destroy Tiptap instance
    if (state.editorInstance) {
      state.editorInstance.destroy();
      state.editorInstance = null;
    }

    // Remove from map
    editors.delete(specRef);
  }

  function unmountAll(): void {
    // Save all dirty editors first
    const promises: Promise<boolean>[] = [];
    for (const [, state] of editors) {
      if (state.debounceTimer !== null) {
        window.clearTimeout(state.debounceTimer);
        state.debounceTimer = null;
      }
      if ((state.dirty || state.needsNormalizationSave) && !state.saving) {
        promises.push(performSave(state));
      }
    }

    // Clean up all
    for (const specRef of Array.from(editors.keys())) {
      unmount(specRef);
    }
    editors.clear();
  }

  function getState(specRef: string): NodeEditorState | undefined {
    return editors.get(specRef);
  }

  function isDirty(specRef: string): boolean {
    return editors.get(specRef)?.dirty ?? false;
  }

  function isSaving(specRef: string): boolean {
    return editors.get(specRef)?.saving ?? false;
  }

  function getError(specRef: string): string | null {
    return editors.get(specRef)?.error ?? null;
  }

  function hasUnsavedChanges(): boolean {
    for (const state of editors.values()) {
      if (state.dirty || state.needsNormalizationSave) return true;
    }
    return false;
  }

  async function save(specRef: string): Promise<boolean> {
    const state = editors.get(specRef);
    if (!state || !state.editorInstance) return false;
    
    // Clear any pending autosave
    if (state.debounceTimer !== null) {
      window.clearTimeout(state.debounceTimer);
      state.debounceTimer = null;
    }
    
    return performSave(state);
  }

  async function saveAll(): Promise<void> {
    const promises: Promise<boolean>[] = [];
    for (const state of editors.values()) {
      if ((state.dirty || state.needsNormalizationSave) && !state.saving) {
        if (state.debounceTimer !== null) {
          window.clearTimeout(state.debounceTimer);
          state.debounceTimer = null;
        }
        promises.push(performSave(state));
      }
    }
    await Promise.all(promises);
  }

  async function flush(specRef: string): Promise<boolean> {
    return save(specRef);
  }

  function remapSpecRef(oldSpecRef: string, newSpecRef: string): void {
    const state = editors.get(oldSpecRef);
    if (!state) return;

    // Update the spec ref in state
    state.specRef = newSpecRef;
    
    // Move to new key
    editors.delete(oldSpecRef);
    editors.set(newSpecRef, state);
  }

  function getUnsavedContent(): Map<string, string> {
    const result = new Map<string, string>();
    for (const [specRef, state] of editors) {
      if ((state.dirty || state.needsNormalizationSave) && state.editorInstance) {
        result.set(specRef, state.editorInstance.storage.markdown.getMarkdown());
      }
    }
    return result;
  }

  function restoreContent(savedContent: Map<string, string>): void {
    for (const [specRef, content] of savedContent) {
      const state = editors.get(specRef);
      if (state && state.editorInstance) {
        const parsed = parseEditorDocument(content, state.title);
        const normalized = normalizeNodeContent(parsed.content);
        state.needsNormalizationSave = state.needsNormalizationSave || normalized.repaired;
        state.title = parsed.title;
        state.content = normalized.normalized;
        if (normalized.repaired) {
          autoRepairedCount += 1;
          console.info(
            `[Tiptap] Auto-repaired escaped HTML content for ${specRef}. Total repaired: ${autoRepairedCount}`
          );
        }
        const editorDocument = composeEditorDocument(
          state.title,
          normalized.normalized,
          state.depth
        );
        state.editorInstance.commands.setContent(editorDocument, true, { preserveWhitespace: 'full' });
      }
    }
  }

  return {
    mount,
    unmount,
    unmountAll,
    getState,
    isDirty,
    isSaving,
    getError,
    hasUnsavedChanges,
    save,
    saveAll,
    flush,
    remapSpecRef,
    getUnsavedContent,
    restoreContent,
  };
}
