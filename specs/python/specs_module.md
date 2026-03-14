- ## Spec Module
    Reads, persists, and mutates the spec tree. In-memory SQLite DB with periodic snapshot, markdown parser, and debounced writeback.
    - {{status: draft}}
    - ### Models (`models.py`)
        Dataclasses for spec tree nodes and mutation payloads. Serialized to/from dicts for RPC transport.
        - {{status: draft}}
        - {{code_ref: `taui/specs/models.py`}}
        - #### SpecFile
            Tracks a markdown file: id, rel_path, content_hash (SHA-256), last_seen timestamp, mtime_ns.
            - {{status: draft}}
        - #### SpecNode
            Core node: id (UUID), spec_ref ("specs/file.md#anchor"), depth, file_path, anchor, markdown, status, code_refs[], verification, collapsed, depends_on[], related_to[].
            Has to_dict() → RPC-safe dict.
            - {{status: draft}}
        - #### SpecNodeDetail
            Extends SpecNode with line_start and line_end (1-based) for source location.
            - {{status: draft}}
        - #### SpecUpdateResult
            Returned by all mutation methods. previous_spec_ref (before any rename), updated SpecNodeDetail, tree_changed bool.
            - {{status: draft}}
        - #### SpecNodePatch
            Patch payload for update_node. Currently supports markdown field only.
            Uses UNSET sentinel object to distinguish "not provided" from null.
            from_mapping() validates field names and types.
            - {{status: draft}}
    - ### Database (`db.py`)
        SpecDB: async SQLite via aiosqlite (falls back to stdlib sqlite3 wrapped with asyncio.Lock when aiosqlite is unavailable).
        - {{status: draft}}
        - {{code_ref: `taui/specs/db.py`}}
        - #### connect() / close()
            Opens in-memory SQLite. Loads snapshot from disk on startup if persist_snapshot=True. Runs schema migrations. Closes and cancels snapshot task on close().
            - {{status: draft}}
        - #### Snapshot system
            Background asyncio.Task persists in-memory DB to disk every snapshot_interval_sec (default 30s).
            Snapshot path: user_cache_dir("taui") / sha256(workspace)[:12] / spec.db.
            Loaded on startup via SQLite backup API to resume between runs.
            - {{status: draft}}
        - #### Schema — spec tables
            files: id, rel_path, content_hash, last_seen, mtime_ns.
            nodes: id, file_id, spec_ref, anchor, depth, heading_level, line_start, line_end, markdown, sort_order, status, code_refs (JSON), verification, collapsed.
            edges: parent_id → child_id.
            node_refs: spec_ref → node_id (index for O(1) lookup).
            - {{status: draft}}
        - #### Schema — agent tables
            agent_sessions: agent_id, session_id, spec_ref, task, tier, model, state, parent_agent_id.
            agent_messages: session message history per agent.
            agent_tool_calls: tool call log with arguments and results.
            questions: human-in-the-loop question/answer pairs.
            - {{status: draft}}
        - #### upsert_file()
            INSERT OR REPLACE for a tracked markdown file. Returns SpecFile row.
            - {{status: draft}}
        - #### replace_nodes_for_file()
            In one transaction: deletes existing nodes for file_id, inserts new NodeUpsert list, updates node_refs and edges.
            - {{status: draft}}
        - #### get_tree()
            SELECT all nodes ORDER BY sort_order. Returns list[SpecNode].
            - {{status: draft}}
        - #### get_node() / get_node_by_ref()
            get_node(node_id) by primary key. get_node_by_ref(spec_ref) via node_refs index. Both return SpecNodeDetail.
            - {{status: draft}}
        - #### set_node_collapsed()
            UPDATE nodes SET collapsed=? WHERE id=?.
            - {{status: draft}}
        - #### Agent session methods
            create_agent_session(), update_agent_state(), save_message(), save_tool_call().
            Used exclusively by AgentRunner and AgentManager.
            - {{status: draft}}
    - ### Sync (`sync.py`)
        SpecSync: scans spec_root for markdown, parses list-item trees, resolves {{tree:}} includes, and writes everything to DB.
        - {{status: draft}}
        - {{code_ref: `taui/specs/sync.py`}}
        - #### full_sync()
            Iterates all *.md files under spec_root (sorted for stability). For each file: reads text, computes SHA-256, calls upsert_file(), calls _parse_nodes(). After all files parsed, resolves includes and writes edges.
            - {{status: draft}}
        - #### _parse_nodes()
            Calls parse_list_items() to extract ListItems. For each item builds ParsedNode: computes anchor via slugify(), extracts metadata items ({{key: value}} child items), populates status, code_refs, verification, collapsed, depends_on_targets, related_to_targets. Returns nodes[], includes[], in_file_edges[].
            - {{status: draft}}
        - #### {{tree:}} include resolution
            Detects {{tree: [Title](./file.md)}} items. Replaces them with the root node of the target file's parsed tree at the same depth position. Follows chains. Detects cycles.
            - {{status: draft}}
        - #### Edge and sort_order writing
            After include resolution, writes parent→child edges to DB. Assigns monotonic sort_order via depth-first traversal.
            - {{status: draft}}
    - ### Service (`service.py`)
        SpecService: high-level CRUD API over the tree. Coordinates SpecDB, SpecSync, and SpecMarkdownWriter.
        - {{status: draft}}
        - {{code_ref: `taui/specs/service.py`}}
        - #### ensure_initialized()
            Thread-safe lazy init via asyncio.Lock. Connects DB, runs full_sync(). Subsequent calls are no-ops.
            - {{status: draft}}
        - #### defer_writeback()
            Async context manager. Sets writer._deferred=True so per-mutation schedule_writeback() only marks files dirty. On exit flushes all dirty files in one batch.
            Used by AgentRunner to prevent hundreds of individual debounced writes during a task.
            - {{status: draft}}
        - #### get_tree()
            Returns list[SpecNode] from DB. Calls ensure_initialized() first.
            - {{status: draft}}
        - #### get_node(spec_ref)
            Returns SpecNodeDetail. Raises SpecNotFoundError if ref is unknown.
            - {{status: draft}}
        - #### update_node(spec_ref, patch)
            Applies SpecNodePatch. Re-parses new markdown to re-extract metadata (status, code_refs, etc.). Updates DB row. Schedules writeback. Recomputes spec_ref if anchor changed. Returns SpecUpdateResult.
            - {{status: draft}}
        - #### create_sibling_node(spec_ref)
            Inserts a blank node after target in parent's child list. Assigns new UUID, anchor="new-node", spec_ref. Updates sort_order for displaced siblings. Schedules writeback. Returns SpecUpdateResult.
            - {{status: draft}}
        - #### indent_node(spec_ref)
            Reparents node to become the last child of its previous sibling. Updates edges and sort_order. Raises SpecValidationError if no previous sibling exists. Returns SpecUpdateResult.
            - {{status: draft}}
        - #### outdent_node(spec_ref)
            Promotes node to the level of its current parent (inserted after parent in grandparent's child list). Updates edges and sort_order. Raises SpecValidationError if already at root. Returns SpecUpdateResult.
            - {{status: draft}}
        - #### set_node_collapsed(spec_ref, collapsed)
            Delegates to DB.set_node_collapsed(). Returns updated SpecNodeDetail.
            - {{status: draft}}
    - ### Writer (`writer.py`)
        SpecMarkdownWriter: reconstructs and writes markdown files from DB rows, with debouncing.
        - {{status: draft}}
        - {{code_ref: `taui/specs/writer.py`}}
        - #### schedule_writeback(file_id)
            Marks file dirty (_pending set). In normal mode: cancels any existing debounce task for the file and starts a new asyncio.create_task with a 500ms sleep. In deferred mode: only marks dirty.
            - {{status: draft}}
        - #### write_file(file_id)
            Reads all node rows for the file from DB. Reconstructs indented list markdown: heading prefix, continuation lines, metadata items (status, code_refs, verification). Writes to disk.
            - {{status: draft}}
        - #### flush() / flush_all_files()
            flush(file_id): immediately writes one file without waiting for debounce.
            flush_all_files(): writes all files in the _pending set.
            - {{status: draft}}
    - ### Markdown (`markdown.py`)
        Utility functions for parsing list-item trees and anchor generation.
        - {{status: draft}}
        - {{code_ref: `taui/specs/markdown.py`}}
        - #### parse_list_items(lines)
            Converts raw markdown line list to list[ListItem]. Detects -, *, + markers. Computes depth from leading spaces (÷ indent_size, default 4). Captures continuation lines (non-list indented lines following an item).
            - {{status: draft}}
        - #### slugify(value)
            Converts string to lowercase ASCII alphanumeric anchor slug. Runs of non-alnum chars become a single dash. Strips leading/trailing dashes.
            - {{status: draft}}
        - #### strip_inline_metadata(value)
            Removes all {{...}} tokens from a string. Collapses whitespace.
            - {{status: draft}}
        - #### parse_markdown_link(line)
            Extracts (text, target) from the first `[text](target)` in a string. Returns None if no valid link found.
            - {{status: draft}}
        - #### markdown_anchor_text(markdown)
            Returns the first line of a markdown string, stripped of inline metadata. Used to compute display title.
            - {{status: draft}}
    - ### Errors (`errors.py`)
        Domain exception hierarchy for spec layer failures.
        - {{status: draft}}
        - {{code_ref: `taui/specs/errors.py`}}
        - #### SpecNotFoundError
            Raised when lookup by spec_ref, node_id, or file path returns nothing.
            - {{status: draft}}
        - #### SpecValidationError
            Raised when a mutation is structurally invalid: bad patch fields, no previous sibling for indent, outdent at root, etc.
            - {{status: draft}}
        - #### SpecServiceError
            Base class for general service-layer failures not covered by the above.
            - {{status: draft}}
