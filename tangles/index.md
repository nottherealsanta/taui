---
title: Taui
last_updated: 2026-04-11
---

# Taui

An agentic coding interface from the future. Users collaborate with agents to write tangles — literate-programming-style documents where prose and code references are interwoven — and agents generate code from them.

## Purpose

- Taui is a tool for building software through **structured intent**
  - Users and agents co-author **tangles**: living documents describing what the system should do
  - Tangles are grounded in dense references to the actual code
- The tangle is the source of truth; code is the derived artifact

## How to Use This Directory

- Start here for a project overview and links to every domain
- Move into `domains/` for subsystem-level context (backend, frontend, tangle module, agent system, server)
- Move into `features/` for specific capabilities (stateless UI, editable prompts, tangle parsing)
- Check `decisions/` for architectural decision records
- Follow code references — the UI renders referenced code inline

## Global Constraints

- **Stack**: Svelte 5 + Tauri + Python/FastAPI + WebSocket JSON-RPC + SQLite
- **Tangle format**: Only `title` and `last_updated` required in frontmatter
  - Everything else is body content shaped by the tangle-maker prompt
- **All paths relative to project root**
  - `src/auth.py` means `<project>/src/auth.py`
  - `tangles/auth.md` means `<project>/tangles/auth.md`
- **Backend is the single source of truth**
  - UI holds no authoritative state
  - All persistent state lives in the backend DB or `settings.json`
- **Project-local storage**
  - `tangles/.taui.db` (gitignored) — runtime/derived data
  - `.taui/settings.json` (optionally tracked) — user settings
- **User-editable prompts**: agent system prompts ship with defaults; users can view and edit them in Settings

## Domains

- [Backend](domains/backend.md) — Python backend: FastAPI server, WebSocket JSON-RPC, SQLite persistence
- [Frontend](domains/frontend.md) — Svelte 5 + Tauri desktop app: three-column layout, stateless stores
- [Tangle Module](domains/tangle-module.md) — Core tangle subsystem: parsing, storage, sync, code ref extraction
- [Agent System](domains/agent-system.md) — Prime, root, and sub agents: LLM orchestration, session management
- [Server](domains/server.md) — RPC handlers, state management, connection lifecycle

## Core Architecture

Three-layer architecture:

- **Frontend** (`app/`) — Svelte 5 + Tauri
  - Obsidian-like three-column layout: left nav, center editor, right agent pane
  - Stateless — all persistent state comes from backend via WebSocket
- **Backend** (`taui/`) — Python/FastAPI
  - WebSocket JSON-RPC server
  - Manages tangle files, agent sessions, and all state
  - Reads/writes `tangles/.taui.db` (runtime) and `.taui/settings.json` (preferences)
- **Storage** — two project-local stores plus global auth
  - `tangles/.taui.db` — SQLite: tangle index, parsed nodes/refs/links, agent sessions, message history (gitignored)
  - `.taui/settings.json` — JSON: tabs, layout, theme, editable prompts (optionally git-tracked)
  - `~/.taui/` — global auth tokens only

**Communication**: Frontend ↔ Backend over WebSocket JSON-RPC. UI sends intents (`ui.openTab`, `tangle.updateNode`); backend processes and pushes state updates.

## Active Features

- [Stateless UI](features/stateless-ui.md) — Backend-driven UI state with snapshot/reconnect protocol
- [Editable Prompts](features/editable-prompts.md) — User-customizable agent system prompts
- [Tangle Parsing](features/tangle-parsing.md) — Markdown → structured data with code ref and link extraction
- [Tangle Sync](features/tangle-sync.md) — Filesystem ↔ DB synchronization for tangle documents
- [Progressive Disclosure](features/progressive-disclosure.md) — Collapsible nested lists in the tangle editor for controlling visible depth

## Key Decisions

- [Minimal Frontmatter](decisions/0001-minimal-frontmatter.md) — Only `title` + `last_updated` in frontmatter; structure is prompt-driven

## Agent Working Rules

- Always read `tangles/index.md` first for project-wide context
- Move to the relevant domain tangle before working in a subsystem
- Move to the relevant feature tangle for task-level context
- Update `last_updated` when meaningfully changing a tangle
- Reference code densely using `file_path:symbol` or `file_path:line_range` notation
- Link to other tangles using standard markdown links: `[Name](tangles/path.md)`
- Do not duplicate code in tangles — reference it; the UI renders code refs inline
