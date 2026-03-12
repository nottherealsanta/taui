# Fix Plan: Keyboard UX, Selection Highlight, and Empty Node Placeholder

Three bugs to fix in `ui/src/app/mod.rs`.

---

## Bug 1: Enter and Shift+Enter do not work as intended

### Problem

**Enter** currently splits the node at the cursor position in editing mode. On an
**empty node**, the user expects Enter to simply create a new sibling below (not
split an empty string). The split path works but produces an awkward empty-before-
empty result.

**Shift+Enter** is not explicitly handled. The `handle_key_down` match arm for
`"enter"` has the guard `!shift`, so Shift+Enter falls through to `return false`
(line 816), passing the event to the Input widget. The Input widget may or may not
insert a `\n`; behavior is unreliable. The spec says Shift+Enter should insert a
literal newline within the current node text.

### Root cause

- `mod.rs:627` — Enter guard excludes `shift`, so Shift+Enter is never matched.
- No explicit `"enter" if shift` arm exists.
- Empty-node Enter goes through the split path which works mechanically but is
  suboptimal (splits `""` into `""` + `""`).

### Fix

In `handle_key_down`, inside the `if input_focused` block (editing mode), **add a
Shift+Enter arm before the existing Enter arm**:

```rust
// Shift+Enter: insert newline within node
"enter" if shift && !ctrl && !alt && !meta => {
    // Insert a literal newline at the cursor position.
    // Read cursor byte offset, splice "\n" into the text, update input.
    let text = self.markdown_input.read(cx).value().to_string();
    let byte_off = {
        let input = self.markdown_input.read(cx);
        let p = input.cursor_position();
        Self::pos_to_byte_offset(&text, p.line, p.character)
    };
    let mut new_text = String::with_capacity(text.len() + 1);
    new_text.push_str(&text[..byte_off]);
    new_text.push('\n');
    new_text.push_str(&text[byte_off..]);

    // Compute the new cursor: next line, column 0.
    let new_line = {
        let input = self.markdown_input.read(cx);
        input.cursor_position().line + 1
    };

    self.markdown_input.update(cx, |state, cx| {
        state.set_value(&new_text, window, cx);
        state.set_cursor_position(
            gpui_component::input::Position::new(new_line, 0),
            window, cx,
        );
    });
    cx.notify();
    return true; // consumed
}
```

**Location:** `mod.rs`, insert before line 627 (the existing `"enter" if !shift`
arm), still inside the `if input_focused { match key.as_str() { ... } }` block.

---

## Bug 2: Tab and Shift+Tab do not work as intended

### Problem

Tab/Shift+Tab are intercepted at lines 592-610 **before** checking whether the
input is focused. They always call `apply_structural(IndentNode / OutdentNode)`.
This is correct structurally, but after the indent/outdent:

1. **In Selection mode:** The code only re-enters editing if
   `self.editor_mode == EditorMode::Editing` (line 601). In Selection mode,
   Tab/Shift+Tab moves the node but the user stays in Selection mode -- they lose
   track of which node just moved because the highlight may not update correctly.
2. **In Editing mode:** The re-focus logic (lines 602-607) calls `select_node()`
   which rebuilds flat tree and re-sets input value, then focuses the input. This
   _should_ work, but may have a subtle issue: `select_node()` calls
   `set_value()` which resets the cursor to position 0. If the user was mid-text,
   cursor position is lost after Tab.

### Fix

After the `apply_structural` call, add a branch for Selection mode that re-selects
the node in selection mode (to update highlights), and in Editing mode, preserve
the cursor position:

```rust
if key == "tab" {
    self.save_current_edits(cx);
    if shift {
        self.apply_structural(UiAction::OutdentNode, cx);
    } else {
        self.apply_structural(UiAction::IndentNode, cx);
    }
    match self.editor_mode {
        EditorMode::Editing => {
            if let Some(selected) = self.state.selected_node {
                // Remember cursor position before select_node resets it.
                let (cur_line, cur_char) = {
                    let input = self.markdown_input.read(cx);
                    let p = input.cursor_position();
                    (p.line, p.character)
                };
                self.select_node(selected, window, cx);
                self.markdown_input.update(cx, |state, cx| {
                    state.set_cursor_position(
                        gpui_component::input::Position::new(cur_line, cur_char),
                        window, cx,
                    );
                    state.focus(window, cx);
                });
            }
        }
        EditorMode::Selection => {
            if let Some(selected) = self.state.selected_node {
                self.select_node_no_edit(selected, cx);
            }
        }
        EditorMode::Normal => {}
    }
    return true;
}
```

**Location:** `mod.rs`, replace lines 592-610.

---

## Bug 3: Selection mode highlights all ancestor nodes (should only highlight the selected node + its children)

### Problem

In `render_node()` (line 1196), `subtree_highlighted` is computed as:

```rust
let subtree_highlighted = self.editor_mode == EditorMode::Selection
    && self.subtree_contains_selected(node_id);
```

`subtree_contains_selected(node_id)` returns `true` if `node_id` **is** the
selected node OR has the selected node as a **descendant**. This means every
**ancestor** of the selected node also gets `subtree_highlighted = true`, causing
the blue background to be applied to every node from the root down to the selected
node -- effectively highlighting the entire path from root to the selected node.

The intended behavior: only the selected node and its **own children/descendants**
should be highlighted, not its ancestors.

### Root cause

`subtree_contains_selected()` answers "does my subtree contain the selection?" --
which is true for every ancestor of the selected node. The check should instead be
"am I the selected node, or is my parent/ancestor the selected node?"

### Fix

Replace the `subtree_highlighted` logic in `render_node()` with a parameter that
propagates **downward** from the selected node, not upward.

Change `render_node` signature to accept `ancestor_is_selected: bool`:

```rust
fn render_node(
    &mut self,
    node_id: NodeId,
    is_root: bool,
    ancestor_is_selected: bool,   // NEW
    window: &mut Window,
    cx: &mut Context<Self>,
) -> gpui::AnyElement {
```

Then compute the highlight:

```rust
let is_selected = self.state.selected_node == Some(node_id);
let subtree_highlighted = self.editor_mode == EditorMode::Selection
    && (is_selected || ancestor_is_selected);
```

And propagate to children:

```rust
// Propagate: children of a selected/highlighted node are also highlighted
let child_ancestor_selected = is_selected || ancestor_is_selected;
let child_els: Vec<gpui::AnyElement> = children_ids
    .iter()
    .map(|&cid| self.render_node(cid, false, child_ancestor_selected, window, cx))
    .collect();
```

Update all call sites to pass `false` for the initial call:
- `mod.rs:1360` -- `self.render_node(id, true, false, window, cx)`
- `mod.rs:1373` -- `self.render_node(id, false, false, window, cx)`

Remove `subtree_contains_selected()` (lines 1244-1257) -- it is no longer needed.

**Location:** `mod.rs`, modify `render_node` (lines 1151-1242) and its two call
sites (lines 1360, 1373).

---

## Bug 4: No placeholder for empty nodes

### Problem

When a node has empty markdown, the view mode renders it as a single space `" "`
(line 1046-1050). This is invisible to the user -- empty nodes appear as blank
rows with no visual affordance indicating they exist or can be edited. The Input
widget has a placeholder `"Markdown..."` configured (line 98) but this only
appears in editing mode.

### Fix

In the **view mode** branch of `render_row()` (the `else` at line 1070), when
`row.markdown.trim().is_empty()`, render a styled placeholder string instead of
a space:

```rust
let content_area = if is_active_editor {
    // ... existing editor branch unchanged ...
} else {
    let is_empty = row.markdown.trim().is_empty();
    if is_empty {
        // Placeholder for empty nodes in view mode
        div()
            .flex_1()
            .cursor_text()
            .on_mouse_down(
                MouseButton::Left,
                cx.listener(move |this, _event, window, cx| {
                    this.select_node(node_id, window, cx);
                    this.markdown_input.update(cx, |state, cx| {
                        state.focus(window, cx);
                    });
                }),
            )
            .child(
                div()
                    .text_color(rgb(colors.text_placeholder))
                    .text_size(MARKDOWN_TEXT_SIZE)
                    .line_height(relative(MARKDOWN_LINE_HEIGHT))
                    .child("Type something..."),
            )
    } else {
        // ... existing markdown TextView branch ...
    }
};
```

Remove the `" "` fallback on line 1046-1050 (no longer needed since empty nodes
now get explicit placeholder rendering).

**Location:** `mod.rs`, lines 1046-1092 in `render_row()`.

---

## Summary of changes

| File | Lines | Change |
|------|-------|--------|
| `mod.rs` | ~627 | Add `"enter" if shift` arm for Shift+Enter newline insertion |
| `mod.rs` | 592-610 | Rewrite Tab/Shift+Tab to preserve cursor and handle Selection mode |
| `mod.rs` | 1151-1257 | Replace `subtree_contains_selected()` with downward `ancestor_is_selected` param |
| `mod.rs` | 1360, 1373 | Update `render_node` call sites with new parameter |
| `mod.rs` | 1046-1092 | Add placeholder rendering for empty nodes in view mode |

All changes are in a single file: `ui/src/app/mod.rs`.

## Verification

After all changes:
1. `cargo build` -- must compile cleanly
2. `cargo test` -- all 62 tests must pass
3. Manual check: Shift+Enter inserts newline, Enter splits/creates sibling, Tab preserves cursor, selection highlights only selected subtree, empty nodes show placeholder
