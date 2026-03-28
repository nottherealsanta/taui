# Plan: Transform Taui into an Obsidian-like Interface

## Current State

The app is a single-pane interface: a spec tree (left/center) with a slide-in agent panel (right) and a bottom drawer for code/terminal. All content is viewed/edited inline within the tree rows.

## Target State

An Obsidian-like multi-pane workspace: file tree sidebar (left), tabbed markdown editor (center), and integrated agent/outline panels (right), with search, backlinks, graph view, and frontmatter display.

---

## Phase 1: Layout Restructuring

### 1.1 — New Layout Shell (`App.svelte`)

Replace the current single-pane layout with a three-column resizable layout:

- **Left sidebar** (resizable, ~250px): File tree browser
- **Center pane** (flex-grow): Tabbed editor area
- **Right sidebar** (resizable, collapsible): Agent panel / Outline / Backlinks

Keep: TitleBar, MessageBar (bottom), Toast, CommandPalette, QuickJump modals.

### 1.2 — Resizable Panels

Create a `SplitPane.svelte` component for drag-to-resize between panels. Store widths in localStorage.

---

## Phase 2: File Tree Sidebar (Left)

### 2.1 — Backend: New Filesystem RPC Endpoints

Add new JSON-RPC methods to the Python backend:

| Method | Params | Returns | Description |
|--------|--------|---------|-------------|
| `fs/listDir` | `{ path: string }` | `{ entries: FileEntry[] }` | List files/folders in a directory |
| `fs/readFile` | `{ path: string }` | `{ content: string, frontmatter?: object }` | Read file content with parsed frontmatter |
| `fs/watchDir` | `{ path: string }` | notification stream | Watch for changes |

`FileEntry` type: `{ name: string, path: string, isDir: boolean, extension: string }`

### 2.2 — Frontend: New Types

Add to `$types/index.ts`:

```typescript
interface FileEntry {
  name: string
  path: string      // relative to workspace root
  isDir: boolean
  extension: string
}

interface OpenTab {
  id: string         // unique tab ID
  filePath: string
  title: string
  isDirty: boolean
  content: string
  frontmatter?: Record<string, unknown>
}
```

### 2.3 — `FileTreeSidebar.svelte` (New Component)

- Header: "SPEC" label with collapse/expand all buttons
- Recursive folder/file tree with:
  - Folder expand/collapse (chevron icons)
  - File icons based on extension (`.md` files)
  - Click to open file in center editor tab
  - Right-click context menu (rename, delete, new file, new folder)
  - Drag-and-drop reordering (stretch goal)
- Lazy-loads directory contents via `fs/listDir`
- Watches for filesystem changes via `fs/watchDir` notifications

### 2.4 — `FileTreeItem.svelte` (New Component)

Individual row in the file tree. Handles indent, icon, label, active/selected state.

### 2.5 — File Tree Store (`file-tree.svelte.ts`)

New Svelte 5 rune-based store managing:

- `entries: Map<string, FileEntry[]>` — cached directory listings
- `expandedDirs: Set<string>` — which folders are open
- `selectedFile: string | null` — currently highlighted file
- Methods: `loadDir()`, `toggleDir()`, `refresh()`

---

## Phase 3: Tabbed Editor (Center Pane)

### 3.1 — `TabBar.svelte` (New Component)

- Horizontal tab bar at top of center pane
- Each tab shows: file name, dirty indicator (dot), close button
- Tab reordering via drag-and-drop
- Middle-click to close, right-click for context menu
- "No tabs open" empty state with welcome/instructions

### 3.2 — `EditorPane.svelte` (New Component)

- Container for the active tab's content
- Renders a markdown editor (Monaco or Milkdown) for `.md` files
- Source mode / Live preview toggle (like Obsidian)
- File-level save (Cmd+S triggers `fs/writeFile` or `spec/updateNode`)

### 3.3 — `MarkdownEditor.svelte` (New Component)

Rich markdown editing experience:

- Uses the existing Monaco editor for source mode
- Consider Milkdown (already a dependency) for live preview / WYSIWYG mode
- Renders YAML frontmatter in a structured properties panel at the top (like Obsidian)
- Syntax highlighting for code blocks
- Internal link support (`[[spec-name]]` style or `[text](specs/path.md)`)

### 3.4 — Tab Store (`tabs.svelte.ts`)

New store managing open tabs:

- `tabs: OpenTab[]`
- `activeTabId: string | null`
- Methods: `openFile()`, `closeTab()`, `setActiveTab()`, `markDirty()`, `save()`
- Persist open tabs to localStorage for session restoration

---

## Phase 4: Right Sidebar

### 4.1 — `RightSidebar.svelte` (New Component)

Collapsible right sidebar with switchable panels:

- **Outline** tab: Table of contents (headings) for the current file
- **Backlinks** tab: Files that link to the current file
- **Agent** tab: Existing `AgentDetailPanel` functionality

### 4.2 — `OutlinePanel.svelte` (New Component)

- Parses the current file's markdown headings
- Shows clickable heading tree (H1 > H2 > H3...)
- Highlights the heading closest to the cursor position
- Click to scroll editor to that heading

### 4.3 — `BacklinksPanel.svelte` (New Component)

Backend: Add `spec/getBacklinks` RPC method returning files that reference the current file.
Frontend: Display list of linking files with context snippets. Click to open the linking file.

### 4.4 — Agent Integration

Move existing `AgentDetailPanel` into the right sidebar as a tab. The `MessageBar` stays at the bottom of the whole window. Agent events continue to stream into the panel as before.

---

## Phase 5: Search

### 5.1 — Backend: `fs/search` RPC

Add full-text search across spec files:

- Params: `{ query: string, regex?: boolean, caseSensitive?: boolean }`
- Returns: `{ results: SearchResult[] }` with file path, line number, context snippet

### 5.2 — `SearchPanel.svelte` (New Component)

- Toggle via Cmd+Shift+F or sidebar icon
- Search input with options (regex, case-sensitive, file filter)
- Results grouped by file, click to open file at matching line
- Can replace the file tree in the left sidebar or be its own panel

---

## Phase 6: Frontmatter Display

### 6.1 — `FrontmatterProperties.svelte` (New Component)

Shown at the top of the editor pane when a file has YAML frontmatter:

- Renders each frontmatter field as a labeled row
- Editable fields (title, status, type, owners, etc.)
- Special rendering for arrays (tags, depends_on), links (code_refs), and dates
- Collapse/expand toggle

---

## Phase 7: Quick Switcher Enhancement

### 7.1 — Update `QuickJump.svelte`

Modify the existing QuickJump (Cmd+P/Cmd+O) to search across actual filesystem files, not just spec nodes. Include fuzzy matching on file paths and heading content.

---

## Phase 8: Graph View (Stretch)

### 8.1 — Backend: `spec/getGraph` RPC

Returns nodes and edges for all spec files based on `depends_on`, `related_to`, and inline links.

### 8.2 — `GraphView.svelte` (New Component)

- Force-directed graph using a library like `d3-force` or `force-graph`
- Each node = a spec file, edges = links between them
- Click a node to open the file
- Toggle via Command Palette or dedicated button

---

## File Change Summary

| Action | File | Description |
|--------|------|-------------|
| **Modify** | `App.svelte` | Replace layout with 3-column resizable panes |
| **Modify** | `app-state.svelte.ts` | Add file tree and tab state (or create new stores) |
| **Modify** | `types/index.ts` | Add FileEntry, OpenTab, SearchResult types |
| **Modify** | `backend-client.ts` | Add `fs/listDir`, `fs/readFile`, `fs/search`, `spec/getBacklinks` RPC methods |
| **Modify** | `QuickJump.svelte` | Search filesystem files instead of only spec nodes |
| **Create** | `SplitPane.svelte` | Resizable panel divider |
| **Create** | `FileTreeSidebar.svelte` | Left sidebar file/folder browser |
| **Create** | `FileTreeItem.svelte` | Individual file tree row |
| **Create** | `file-tree.svelte.ts` | File tree state store |
| **Create** | `TabBar.svelte` | Editor tab bar |
| **Create** | `EditorPane.svelte` | Center editor container |
| **Create** | `MarkdownEditor.svelte` | Rich markdown editing |
| **Create** | `tabs.svelte.ts` | Tab management store |
| **Create** | `RightSidebar.svelte` | Right sidebar container |
| **Create** | `OutlinePanel.svelte` | Document outline/TOC |
| **Create** | `BacklinksPanel.svelte` | Backlinks display |
| **Create** | `SearchPanel.svelte` | Full-text search UI |
| **Create** | `FrontmatterProperties.svelte` | Frontmatter property editor |
| **Create** | `GraphView.svelte` | Link graph visualization |
| **Modify** | Python backend | Add filesystem RPC handlers, backlinks endpoint, search endpoint |

## Implementation Order

1. **Phase 1** — Layout shell (SplitPane + 3-column layout in App.svelte)
2. **Phase 2** — File tree sidebar (backend RPC + FileTreeSidebar + store)
3. **Phase 3** — Tabbed editor (TabBar + EditorPane + MarkdownEditor + tabs store)
4. **Phase 4** — Right sidebar (Outline + Backlinks + Agent tabs)
5. **Phase 5** — Search
6. **Phase 6** — Frontmatter display
7. **Phase 7** — Quick switcher enhancement
8. **Phase 8** — Graph view

Phases 1-3 form the core Obsidian-like experience. Phases 4-8 are additive features that can be built incrementally.
