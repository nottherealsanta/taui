# Spec Standards Migration Plan

Migrate `tests/example_project/specs/` to the new spec standard, then update the parser and tests to handle the new format.

---

## Phase 1: Migrate `tests/example_project/specs/`

### Current state

```
tests/example_project/specs/
  _main.md          # Root: "Example Project Simple" with 3 domains inlined
  task_board.md     # Task board CRUD workflows
  database_schema.md # Users + Tasks tables
```

Format: custom indented-bullet tree with `{{status:}}`, `{{code_ref:}}`, `{{verification:}}`, `{{depends_on:}}`, `{{tree:}}` metadata tags. No YAML frontmatter. Entry point is `_main.md`.

### Target state

```
tests/example_project/specs/
  main.md
  standards.md
  architecture.md
  domains/
    task-management.md
    authentication.md
    data-layer.md
  features/
    create-task.md
    edit-task.md
    delete-task.md
    login.md
    logout.md
  decisions/
    (empty directory, .gitkeep)
```

### File-by-file spec

#### `main.md`

```yaml
---
title: Example Project
status: active
last_updated: 2026-03-20
---
```

Headings: `# Project Spec`, `## Purpose`, `## How to Use This Directory`, `## Global Constraints`, `## Domains`, `## Core Architecture`, `## Active Features`, `## Key Decisions`, `## Agent Working Rules`.

Content:
- Purpose: "A simplified example project demonstrating task management with boards and cards, user authentication, and a data layer."
- Domains: links to `domains/task-management.md`, `domains/authentication.md`, `domains/data-layer.md`
- Active Features: links to all 5 feature files
- Key Decisions: "No decisions recorded yet."

#### `standards.md`

```yaml
---
title: Spec Standards
status: active
last_updated: 2026-03-20
---
```

Body: "This project follows the spec standards defined in the root project. See `../../spec_standards.md` for the full standard."

#### `architecture.md`

```yaml
---
title: Architecture
status: active
last_updated: 2026-03-20
---
```

Headings: `# Architecture`, `## Overview`, `## Components`, `## Data Flow`.

Content: Brief description of the three-area system: task management (boards/cards), authentication (login/logout), data layer (database models). References `src/task_board.py`, `src/auth.py`, `src/database.py`.

#### `domains/task-management.md`

```yaml
---
title: Task Management
status: active
domain: task-management
depends_on:
  - specs/domains/data-layer.md
code_refs:
  - src/task_board.py
test_refs:
  - tests/example_project/tests/test_task_board.py
last_updated: 2026-03-20
---
```

Required headings: Responsibility, Invariants, Interfaces, Key Components, Important Code References, Verification, Related Features, Related Decisions.

Content derived from current `_main.md` Task Management section + `task_board.md`:
- Responsibility: "Basic task tracking with boards and cards. Owns card creation, editing, deletion, and organization workflows."
- Invariants: (from current data — card creation requires persistence, updates depend on creation)
- Key Components: Task board with create/update/delete/organize card workflows
- Code refs: `src/task_board.py`
- Verification: `pytest tests/example_project/tests/test_task_board.py -q`
- Related Features: links to `features/create-task.md`, `features/edit-task.md`, `features/delete-task.md`

#### `domains/authentication.md`

```yaml
---
title: Authentication
status: active
domain: authentication
code_refs:
  - src/auth.py
last_updated: 2026-03-20
---
```

Content derived from current `_main.md` Authentication section:
- Responsibility: "User authentication system. Owns login and logout flows."
- Related Features: links to `features/login.md`, `features/logout.md`

#### `domains/data-layer.md`

```yaml
---
title: Data Layer
status: active
domain: data-layer
code_refs:
  - src/database.py
last_updated: 2026-03-20
---
```

Content derived from current `_main.md` Data Layer section + `database_schema.md`:
- Responsibility: "Database abstraction and operations. Defines data models and relationships."
- Key Components: Users table (`src/database.py#L1-L20`), Tasks table (`src/database.py#L22-L45`)

#### `features/create-task.md`

```yaml
---
title: Create Task
status: active
domain: task-management
depends_on:
  - specs/domains/task-management.md
code_refs:
  - src/task_board.py#L1-L45
test_refs:
  - tests/example_project/tests/test_task_board.py::test_create_card
last_updated: 2026-03-20
---
```

Required headings: Purpose, User / Business Outcome, Scope, Constraints, Design, Code References, Tests / Verification, Open Questions, Related Decisions.

Content:
- Purpose: "Add new tasks to a board. Ability to create a task with title and description."
- Verification: `pytest tests/example_project/tests/test_task_board.py::test_create_card -q`

#### `features/edit-task.md`

```yaml
---
title: Edit Task
status: draft
domain: task-management
depends_on:
  - specs/domains/task-management.md
  - specs/features/create-task.md
code_refs:
  - src/task_board.py#L47-L89
last_updated: 2026-03-20
---
```

Content:
- Purpose: "Modify existing tasks. Update title, description, or assignee."
- Constraints: "Depends on Create Task — cannot edit a task that doesn't exist."

#### `features/delete-task.md`

```yaml
---
title: Delete Task
status: draft
domain: task-management
depends_on:
  - specs/domains/task-management.md
last_updated: 2026-03-20
---
```

Content:
- Purpose: "Remove tasks from the board. Soft-delete by archiving."

#### `features/login.md`

```yaml
---
title: Login
status: active
domain: authentication
depends_on:
  - specs/domains/authentication.md
code_refs:
  - src/auth.py#L1-L30
last_updated: 2026-03-20
---
```

Content:
- Purpose: "User login with credentials."
- Verification: "Manual testing with valid credentials."

#### `features/logout.md`

```yaml
---
title: Logout
status: draft
domain: authentication
depends_on:
  - specs/domains/authentication.md
last_updated: 2026-03-20
---
```

Content:
- Purpose: "End user session."

### Files to delete

- `tests/example_project/specs/_main.md`
- `tests/example_project/specs/task_board.md`
- `tests/example_project/specs/database_schema.md`

---

## Phase 2: Update Parser to Handle New Format

The parser currently expects the custom indented-bullet tree format. It must be updated to also parse conventional markdown with YAML frontmatter.

### 2.1 `taui/specs/markdown.py`

#### Current behavior

- `parse_list_items()` (line 82): Parses lines looking for `- `, `* `, `+ ` markers at indent levels. Returns `ListItem` objects with `depth`, `title`, `line_index`, `parent_index`, `content_lines`.
- `strip_inline_metadata()` (line 64): Removes `{{...}}` tokens.
- `slugify()` (line 31): Converts text to kebab-case anchor.
- `extract_headings()` (line 131): Extracts `#`-prefixed headings. Already works with standard markdown.

#### Required changes

**New function: `parse_yaml_frontmatter(lines: list[str]) -> tuple[dict, int]`**

Parse YAML frontmatter delimited by `---` fences at the top of a file. Returns the parsed dict and the line index where the body begins.

```python
def parse_yaml_frontmatter(lines: list[str]) -> tuple[dict[str, Any], int]:
    """Parse YAML frontmatter from --- delimited block at top of file.
    
    Returns (metadata_dict, body_start_line_index).
    If no frontmatter found, returns ({}, 0).
    """
```

Implementation:
1. Check if `lines[0].strip() == "---"`.
2. Find the closing `---` line.
3. Parse the YAML between them (use `yaml.safe_load` — add `pyyaml` dependency or use a minimal parser).
4. Return the parsed dict and the line index after the closing `---`.

**New function: `parse_heading_tree(lines: list[str], start: int = 0) -> list[HeadingNode]`**

Parse standard markdown headings into a tree structure (replacing the role of `parse_list_items` for the new format).

```python
@dataclass(slots=True)
class HeadingNode:
    level: int           # heading level (1-6)
    title: str           # heading text
    line_index: int      # 0-based line number
    body_lines: list[str] # lines between this heading and the next
    parent_index: int | None  # index of parent HeadingNode in the list
```

Implementation:
1. Iterate lines from `start`.
2. When a `#`-prefixed line is found, create a `HeadingNode`.
3. Collect body lines until the next heading.
4. Compute `parent_index` from heading levels (a `## B` after `# A` makes A the parent of B).

**Modify `strip_inline_metadata()`**

Keep existing behavior but also add a companion function that can extract metadata from YAML frontmatter:

```python
def extract_metadata_from_frontmatter(fm: dict) -> dict[str, Any]:
    """Normalize frontmatter keys to the internal metadata format."""
```

Maps: `status` → status, `code_refs` → list of code ref strings, `test_refs` → list of test ref strings, `depends_on` → list of dependency paths, etc.

### 2.2 `taui/specs/sync.py`

#### Current behavior

- `SpecSync.full_sync()` (line 68): Iterates `*.md` files, reads text, calls `_parse_nodes()`.
- `_parse_nodes()` (line 236): Calls `parse_list_items()`, iterates items. For each item:
  - Checks for `{{tree:}}` metadata → creates `ParsedInclude`
  - Checks for `{{status:}}`, `{{code_ref:}}` etc. → applies to parent node via `_apply_metadata()`
  - Otherwise creates a `ParsedNode` with anchor, heading_level, markdown, etc.
- `_compute_tree_coordinates()` (line 183): Walks the tree starting from `_main.md`, assigns depth and sort_order.

#### Required changes

**Detect format per file**

Add a function to detect whether a file uses the old format (indented bullets) or the new format (YAML frontmatter):

```python
def _detect_format(self, lines: list[str]) -> str:
    """Return 'legacy' for indented-bullet format, 'standard' for new format."""
    for line in lines[:5]:
        if line.strip() == "---":
            return "standard"
    return "legacy"
```

**New method: `_parse_nodes_standard()`**

A parallel to `_parse_nodes()` that handles the new format:

```python
def _parse_nodes_standard(
    self,
    *,
    file_id: int,
    rel_path: str,
    lines: list[str],
    existing_ids: dict[str, str],
) -> tuple[list[ParsedNode], list[ParsedInclude], list[tuple[str, str]]]:
```

Implementation:
1. Call `parse_yaml_frontmatter(lines)` to extract frontmatter and body start.
2. Call `parse_heading_tree(lines, start=body_start)` to get headings.
3. For each heading, create a `ParsedNode`:
   - `anchor` = `slugify(heading.title)`
   - `heading_level` = heading level
   - `markdown` = heading title + body text
   - `status` = from frontmatter or inline if present
   - `code_refs` = from frontmatter `code_refs` list
   - `verification` = from frontmatter `test_refs` (first entry or joined)
   - `depends_on_targets` = from frontmatter `depends_on` list
4. Build `in_file_edges` from heading parent-child relationships.
5. Build `includes` from frontmatter `depends_on` links to other spec files (not anchors within the same file).

**Modify `_parse_nodes()`**

Update the existing method to call `_detect_format()` and dispatch:

```python
def _parse_nodes(self, *, file_id, rel_path, lines, existing_ids):
    fmt = self._detect_format(lines)
    if fmt == "standard":
        return self._parse_nodes_standard(
            file_id=file_id, rel_path=rel_path, 
            lines=lines, existing_ids=existing_ids,
        )
    # existing logic unchanged for legacy format
    ...
```

**Modify `_compute_tree_coordinates()`**

Update the entry point detection. Currently it looks for `_main.md`:

```python
root_main = self.spec_root / "_main.md"
```

Change to check both:

```python
root_main = self.spec_root / "main.md"
if not root_main.exists():
    root_main = self.spec_root / "_main.md"
```

**Metadata extraction from frontmatter**

The new format stores metadata in YAML frontmatter rather than `{{tag:}}` items. The `_apply_metadata()` method stays for legacy format. For the new format, metadata is extracted during `_parse_nodes_standard()`:

```python
# In _parse_nodes_standard:
fm, body_start = parse_yaml_frontmatter(lines)
root_node.status = fm.get("status")
root_node.code_refs = fm.get("code_refs", [])
root_node.verification = "; ".join(fm.get("test_refs", []))  
# depends_on: each entry is a relative path to another spec file
root_node.depends_on_targets = fm.get("depends_on", [])
```

Frontmatter metadata applies to the **root node of the file** (the `# Title` heading or the file itself if no heading exists). Section-level metadata in the new format is expressed through prose in the body, not through inline tags.

### 2.3 `taui/specs/writer.py`

#### Current behavior

`write_file()` (line 51): Reconstructs indented-bullet markdown from DB rows. For each node:
- Writes `{indent}- {first_line}` 
- Writes continuation lines indented
- Writes `{{status:}}`, `{{code_ref:}}`, `{{verification:}}`, `{{depends_on:}}`, `{{tree:}}` metadata items

#### Required changes

**New method: `write_file_standard()`**

A parallel to `write_file()` for the new format:

```python
async def write_file_standard(self, file_id: int) -> None:
```

Implementation:
1. Read the file row to get `rel_path`.
2. Read nodes for the file.
3. Construct YAML frontmatter from the root node's metadata:
   ```python
   frontmatter = {
       "title": root_node_title,
       "type": infer_type_from_path(rel_path),  # domain/feature/decision/etc.
       "status": root_node.status or "draft",
       "owners": ["team"],
       "last_updated": date.today().isoformat(),
   }
   if root_node.code_refs:
       frontmatter["code_refs"] = root_node.code_refs
   if root_node.verification:
       frontmatter["test_refs"] = [root_node.verification]
   ```
4. Write `---\n{yaml}\n---\n`.
5. For each node, write standard markdown heading at the correct level:
   ```
   ## Heading Title
   
   Body text.
   
   ```
6. No `{{...}}` tags in output.

**Format detection for write**

The writer needs to know which format to use. Options:
- Store the format in the `files` table (new column `format TEXT DEFAULT 'legacy'`).
- Detect from the existing file on disk.
- Use a flag on the SpecService.

Recommended: Add a `format` column to the `files` table. Set to `'standard'` during sync when frontmatter is detected. Writer checks this column.

```python
async def write_file(self, file_id: int) -> None:
    file_row = await self.db.get_file_by_id(file_id)
    if file_row is None:
        return
    if getattr(file_row, 'format', 'legacy') == 'standard':
        return await self.write_file_standard(file_id)
    # existing logic for legacy format
    ...
```

### 2.4 `taui/specs/models.py`

No structural changes needed. The `SpecNode` dataclass already has the right fields (`status`, `code_refs`, `verification`, `depends_on`, `related_to`). These fields are populated differently by the new parser but the model itself is format-agnostic.

### 2.5 `taui/specs/db.py`

#### Schema migration

Add a `format` column to the `files` table:

```sql
ALTER TABLE files ADD COLUMN format TEXT DEFAULT 'legacy';
```

Add this to the migration logic in `connect()` / schema setup. The `upsert_file()` method should accept an optional `format` parameter.

### 2.6 `taui/specs/__init__.py`

No changes needed unless it re-exports something that changes signature.

### 2.7 Dependencies

Add `pyyaml` to project dependencies for YAML frontmatter parsing. Alternatively, implement a minimal frontmatter parser that handles the simple key-value YAML used in frontmatter (to avoid a new dependency).

Minimal parser approach (no new dependency):

```python
def parse_yaml_frontmatter(lines: list[str]) -> tuple[dict[str, Any], int]:
    if not lines or lines[0].strip() != "---":
        return {}, 0
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, 0
    
    result: dict[str, Any] = {}
    current_key = None
    current_list: list[str] | None = None
    
    for line in lines[1:end]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # List item continuation
        if stripped.startswith("- ") and current_key is not None and current_list is not None:
            current_list.append(stripped[2:].strip())
            continue
        # Key-value pair
        if ":" in stripped:
            if current_key and current_list is not None:
                result[current_key] = current_list
                current_list = None
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()
            if value:
                result[key] = value
                current_key = key
            else:
                current_key = key
                current_list = []
            continue
    
    if current_key and current_list is not None:
        result[current_key] = current_list
    
    return result, end + 1
```

---

## Phase 3: Update Tests

### 3.1 Tests that reference `example_project/specs/`

These tests create inline fixtures or reference the example_project specs directory by path. They must be updated to match the new file structure.

#### `tests/test_specs_service.py` — `test_get_tree_uses_custom_specs_path` (line 246)

**Current:** Creates `tests/example_project/specs/_main.md` with content `"- Example Project\n    Example intent.\n"` in `tmp_path`. Asserts `"tests/example_project/specs/_main.md#example-project"` is in the tree.

**Change:** Update to create `tests/example_project/specs/main.md` with YAML frontmatter:

```python
(specs_root / "main.md").write_text(
    "\n".join([
        "---",
        "title: Example Project",
        "type: project",
        "status: active",
        "owners:",
        "  - example-team",
        "last_updated: 2026-03-20",
        "---",
        "",
        "# Project Spec",
        "",
        "## Purpose",
        "",
        "Example intent.",
        "",
    ]),
    encoding="utf-8",
)
```

**Assert change:** `"tests/example_project/specs/main.md#project-spec"` or `"tests/example_project/specs/main.md#example-project"` depending on how `slugify` processes the title from frontmatter vs. first heading.

Decision: The root node's anchor should come from the frontmatter `title` field, not the first heading. This means the parser must use `fm["title"]` as the anchor source for the root node:
- `slugify("Example Project")` → `"example-project"`
- spec_ref: `"tests/example_project/specs/main.md#example-project"`

#### `tests/test_server_app.py` — tail of `test_outdent_node_moves_up_one_level` (line 676)

**Current:** Creates `example_project/specs/_main.md` with `"- Example Project\n    Example intent.\n"`. Asserts `"example_project/specs/_main.md#example-project"`.

**Change:** Same pattern as above — create `main.md` with frontmatter. Assert `"example_project/specs/main.md#example-project"`.

### 3.2 Tests with inline `_write_specs()` helpers

These tests create spec fixtures in `tmp_path` using the old format. They must be updated to create specs in the new format, OR the parser must remain backward-compatible with the legacy format.

**Recommended approach: Keep legacy format support in the parser.** The `_detect_format()` function means `_parse_nodes()` handles both formats. Tests that write old-format specs will continue to work as long as the legacy code path is preserved.

**This means:** The existing `_write_specs()` helpers in test files do NOT need to change immediately. They exercise the legacy parser path. New tests should be added to exercise the standard format path.

#### Files with `_write_specs()` that need NO changes (legacy path still works):

- `tests/test_specs_service.py` — `_write_specs()` at line 15
- `tests/test_server_app.py` — `_write_specs()` at line 14
- `tests/test_agent.py` — `_write_specs()` at line 33
- `tests/test_phase3.py` — `_write_specs()` (creates old-format specs)
- `tests/test_phase3_rpc.py` — `_write_specs()` (creates old-format specs)
- `tests/test_server_startup.py` — `_write_specs()` (creates old-format specs)
- `tests/test_agent_rpc.py` — `_write_specs()` (creates old-format specs)
- `tests/test_phase6.py` — inline spec content at lines 138, 172

### 3.3 New tests to add

#### `tests/test_specs_standard_format.py` (new file)

Tests for the new standard format parser. Mirror the key tests from `test_specs_service.py` but using standard-format spec files.

```python
"""Tests for parsing specs in the new standard format (YAML frontmatter + markdown headings)."""

# Test 1: test_standard_format_get_tree_loads_nodes
# Write main.md with frontmatter, domains/foo.md, features/bar.md
# Assert all nodes appear in tree with correct spec_refs

# Test 2: test_standard_format_frontmatter_metadata_populates_node
# Write a feature file with status, code_refs, test_refs in frontmatter
# Assert node.status, node.code_refs, node.verification are populated

# Test 3: test_standard_format_headings_create_child_nodes
# Write a file with # Title, ## Section A, ## Section B, ### Sub-section
# Assert 4 nodes with correct parent-child edges and depths

# Test 4: test_standard_format_depends_on_creates_refs
# Write two files where file B's frontmatter has depends_on pointing to file A
# Assert the dependency ref is recorded in the DB

# Test 5: test_standard_format_update_node_roundtrips
# Parse a standard file, update a node's markdown, flush to disk
# Assert the file on disk is valid standard format (frontmatter preserved)

# Test 6: test_standard_format_mixed_with_legacy
# Have both _main.md (legacy) and domains/foo.md (standard) in same specs/
# Assert both are parsed correctly — legacy via list items, standard via headings

# Test 7: test_standard_format_entry_point_is_main_md
# Create specs/main.md (not _main.md). Assert it is used as root.
# Assert tree coordinates start from main.md.

# Test 8: test_standard_format_no_frontmatter_falls_back_to_legacy
# Write a file without frontmatter (starts with `- ` bullet)
# Assert it is parsed via legacy path

# Test 9: test_standard_format_writer_produces_valid_output
# Parse a standard file, mutate a node, write back
# Read the file and verify:
#   - YAML frontmatter is present and valid
#   - Headings are standard markdown
#   - No {{...}} tags in output

# Test 10: test_standard_format_slugify_from_frontmatter_title
# File with frontmatter title "My Feature" and heading "# Purpose"
# Root node anchor should be "my-feature" (from frontmatter title)
# Child node anchor should be "purpose" (from heading)
```

#### `tests/test_markdown_frontmatter.py` (new file)

Unit tests for the new `parse_yaml_frontmatter()` function:

```python
"""Unit tests for YAML frontmatter parsing."""

# Test 1: test_parse_frontmatter_basic
# Input: ["---", "title: Foo", "status: active", "---", "", "# Body"]
# Assert: {"title": "Foo", "status": "active"}, body_start=4

# Test 2: test_parse_frontmatter_with_lists
# Input with owners: list, code_refs: list, depends_on: list
# Assert lists are parsed correctly

# Test 3: test_parse_frontmatter_missing
# Input: ["# Just a heading", "Some text"]
# Assert: {}, 0

# Test 4: test_parse_frontmatter_unclosed
# Input: ["---", "title: Foo", "# No closing fence"]
# Assert: {}, 0

# Test 5: test_parse_heading_tree_basic
# Input: ["# A", "Body A", "## B", "Body B", "## C", "### D"]
# Assert 4 HeadingNode objects with correct parent relationships
```

### 3.4 Test for writer standard format

Add to `tests/test_phase6.py` or create a new test:

```python
# Test: test_writer_standard_format_roundtrip
# 1. Create a standard-format spec file on disk
# 2. Run full_sync to parse it
# 3. Update a node via SpecService.update_node()
# 4. Flush writer
# 5. Read file from disk
# 6. Assert frontmatter is preserved
# 7. Assert heading structure is maintained
# 8. Assert updated content appears correctly
```

---

## Phase 4: Implementation Order

### Step 1: `markdown.py` — Add frontmatter parser and heading tree parser

1. Add `parse_yaml_frontmatter()` function
2. Add `HeadingNode` dataclass
3. Add `parse_heading_tree()` function
4. Add `extract_metadata_from_frontmatter()` helper
5. Write `tests/test_markdown_frontmatter.py`
6. Run tests: `pytest tests/test_markdown_frontmatter.py -v`

### Step 2: `sync.py` — Add standard format detection and parsing

1. Add `_detect_format()` method
2. Add `_parse_nodes_standard()` method
3. Modify `_parse_nodes()` to dispatch based on format
4. Modify `_compute_tree_coordinates()` to check `main.md` before `_main.md`
5. Write `tests/test_specs_standard_format.py` (tests 1-4, 6-8)
6. Run tests: `pytest tests/test_specs_standard_format.py -v`
7. Run legacy tests: `pytest tests/test_specs_service.py -v` (must still pass)

### Step 3: `db.py` — Add format column

1. Add `format TEXT DEFAULT 'legacy'` column to `files` table schema
2. Update `upsert_file()` to accept and store `format` parameter
3. Update `SpecFile` model if needed (add `format` field)
4. Run existing tests: `pytest tests/test_specs_db.py -v` (must still pass)

### Step 4: `writer.py` — Add standard format writer

1. Add `write_file_standard()` method
2. Add `_infer_type_from_path()` helper
3. Modify `write_file()` to dispatch based on file format
4. Write roundtrip test (test 5, 9 from standard format tests)
5. Run tests: `pytest tests/test_specs_standard_format.py tests/test_phase6.py -v`

### Step 5: Migrate `tests/example_project/specs/`

1. Delete old files: `_main.md`, `task_board.md`, `database_schema.md`
2. Create new directory structure: `domains/`, `features/`, `decisions/`
3. Write all 11 new spec files per Phase 1 spec above
4. Update `test_get_tree_uses_custom_specs_path` in `test_specs_service.py`
5. Update tail of `test_outdent_node_moves_up_one_level` in `test_server_app.py`
6. Run all tests: `pytest -v`

### Step 6: Verify full test suite

1. `pytest tests/ -v` — all tests must pass
2. Legacy format tests continue passing (backward compatible)
3. New standard format tests pass
4. Example project specs parse correctly in the new format

---

## Risk Assessment

### Breaking changes

1. **Entry point rename** (`_main.md` → `main.md`): The `_compute_tree_coordinates()` method hardcodes `_main.md`. Must check both.

2. **Anchor generation**: Currently anchors come from the list item title (after stripping `#` heading prefixes and metadata). In the new format, the root node anchor should come from the frontmatter `title`, and child anchors from heading text. This changes `spec_ref` values.

3. **Metadata location**: Currently metadata is distributed as `{{tag:}}` items throughout the tree. In the new format, metadata is concentrated in YAML frontmatter at the file level. This means:
   - Only the root node of a file gets `status`, `code_refs`, etc. from frontmatter.
   - Child headings within a file do not carry their own metadata (unless we support inline YAML blocks or comments — not in the standard).
   - This is a semantic change: currently every node can have independent status. In the new format, status is per-file.

4. **Writer backward compatibility**: The writer must produce the correct format for each file. Mixing formats in one `specs/` directory must work.

### Mitigation

- Format detection per file ensures backward compatibility.
- Legacy code paths remain untouched.
- New tests exercise both paths.
- Gradual migration: files can be converted one at a time.

---

## Summary

| Phase | What | Files changed | New files |
|-------|------|---------------|-----------|
| 1 | Migrate example_project specs | 3 deleted | 11 created |
| 2 | Update parser | `markdown.py`, `sync.py`, `writer.py`, `db.py` | — |
| 3 | Update tests | `test_specs_service.py`, `test_server_app.py` | `test_specs_standard_format.py`, `test_markdown_frontmatter.py` |
| 4 | Implementation order | Sequential steps 1-6 | — |
