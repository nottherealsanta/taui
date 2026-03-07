Here’s the **behavior spec** for Logseq-style node editing, without code.

# Editor interaction spec

## 1. Terminology
- **Node / block**: one outline item with editable text.
- **Editing mode**: the node is active and text input goes into it.
- **Selection mode**: focus is on blocks structurally rather than only on text caret.
- **Sibling**: node at same depth.
- **Child**: nested node under a parent.

---

## 2. Entering edit mode
### Trigger
- Click a node
- Keyboard navigation lands on a node and opens it for editing
- A structural action creates a new node and focus moves into it

### Expected behavior
- The target node becomes the active editing target
- Its current text is loaded into the editor
- Caret position is initialized
- Editor state remembers:
  - active node identity
  - container/context
  - cursor position
  - navigation direction if relevant

---

## 3. Editing an existing node
### Normal typing
- Printable characters insert text into the current node
- The node remains the same structural entity
- Edits are buffered until save, focus change, or explicit structural action

### Save boundary
The current node should be committed when:
- focus moves to another node
- user exits editing
- a structural action creates/moves to another block
- another command requires current content to be persisted

### Exit editing
Typical exits:
- Escape
- click away
- structural transition to block selection or another target

Expected result:
- pending edits are saved or reconciled
- editor state is cleared or moved to next active target

---

## 4. Creating a new node
## Action
**Enter**

### Default meaning
Pressing Enter in a node does **not** insert a line break by default.  
It performs a **structural split/create action**.

### Expected behavior
When Enter is pressed:
- current node content is finalized
- a new node is created relative to current structure
- focus moves to the new node
- caret is placed in the new node ready for typing

### Typical placement rules
Depending on context, the new node is usually:
- a **next sibling** of the current node
- or a split-result if Enter is pressed mid-text and the editor supports block splitting

### Empty-node expectations
If current node is empty, Enter may:
- create another empty sibling
- or in some UX variants reduce nesting / outdent / stop list behavior

For a Logseq-like outliner, the main spec expectation is:
- Enter creates the next editable block in outline flow

---

## 5. Creating a new child node
There are two distinct concepts users often mean:

### A. Make current/new node into a child
**Tab**
- Indents the current node
- The node becomes a child of the nearest valid previous sibling
- Focus stays on that node after indentation

### B. Create a fresh child under current node
Usually achieved as:
1. create a new node
2. indent it under the current parent

### Expected child-node behavior
After child creation:
- hierarchy updates immediately
- parent/child visual indentation updates
- navigation treats the node as nested
- expand/collapse behavior applies based on its new parent

---

## 6. Shift+Enter
## Action
**Shift+Enter**

### Meaning
Insert a **newline inside the current node**.

### Expected behavior
- No new block is created
- Current node remains active
- A line break is inserted into the node text
- Caret moves to the next line within the same node

### Why this matters
This distinguishes:
- **Enter** = structure
- **Shift+Enter** = text formatting within one structure node

### Constraints
- Must preserve node identity
- Must not trigger sibling creation
- Must not alter tree depth

---

## 7. Arrow key behavior
Arrow keys have **dual behavior**:
1. normal text-caret movement inside the current node
2. structural navigation between nodes when caret reaches boundaries

---

## 8. ArrowUp
### Inside multiline content
- Moves caret to visual/text line above when possible

### At top boundary of current node
If caret is already at the logical start/top:
- save current edits if needed
- move focus to previous editable node
- place caret appropriately in that target, typically:
  - end of previous node
  - or matching horizontal position when supported

### Structural expectations
- previous node may be:
  - previous sibling
  - deepest visible descendant of previous sibling
  - previous visible block in outline traversal

---

## 9. ArrowDown
### Inside multiline content
- Moves caret to visual/text line below when possible

### At bottom boundary of current node
If caret is already at the logical end/bottom:
- save current edits if needed
- move focus to next editable node
- place caret appropriately in that target, typically:
  - start of next node
  - or matching horizontal position when supported

### Structural expectations
- next node follows visible outline order
- collapsed children are skipped if not visible

---

## 10. ArrowLeft
### Normal text behavior
- Move caret one position left within text

### Structural boundary behavior
When caret is at the far left/start:
- may clear transient editor UI state
- may shift from text-navigation semantics to structure-navigation semantics
- in some editors may move to parent/select block if already at absolute start

### Spec-safe statement
For Logseq-style behavior, ArrowLeft should:
- primarily remain a text navigation key
- at left boundary, participate in editor state transitions rather than immediate text insertion behavior
- not create/delete nodes

---

## 11. ArrowRight
### Normal text behavior
- Move caret one position right within text

### Structural boundary behavior
When caret is at the far right/end:
- may clear transient editor UI state
- may prepare for movement out of current node depending on editor mode
- generally remains text-first unless a boundary rule applies

### Spec-safe statement
ArrowRight should:
- primarily move within text
- participate in boundary-aware editor transitions when the caret is already at the end

---

## 12. Arrow navigation across nodes
When arrow navigation crosses from one node to another, the editor should:
- persist current text if it changed
- resolve the next visible target node
- move focus to that node
- set caret position based on direction/context
- preserve smooth keyboard-only traversal through the outline

This is essential to the “outliner” feel:
- arrows are not only text navigation
- they are also block traversal keys at boundaries

---

## 13. Selection-modified arrows
### Shift+ArrowUp / Shift+ArrowDown
Expected role:
- extend selection upward/downward
- may operate on text selection or block selection depending on mode/context

### Alt+ArrowUp / Alt+ArrowDown or equivalent block shortcuts
Expected role:
- move structural selection between blocks
- may enter/select neighboring blocks without free-text caret behavior

The exact modifier semantics can vary by mode, but the spec should distinguish:
- **plain arrows** = text-first, structure at boundaries
- **shift + arrows** = selection extension
- **alt/mod + arrows** = structural/block operations

---

## 14. Interaction with autocomplete / transient UI
When autocomplete, slash-command menus, or inline pickers are open:
- Enter may confirm selection instead of creating a block
- Shift+Enter may invoke alternate completion behavior in that UI
- ArrowUp/ArrowDown may navigate menu items instead of blocks

### Spec rule
Transient UI takes priority over normal editor key handling while active.

---

## 15. Interaction with parent/child visibility
If nodes can be collapsed:
- Arrow navigation should follow **visible outline order**
- hidden children should not receive focus unless expanded
- creating a child under a collapsed parent may require auto-expansion or predictable hidden insertion behavior

Preferred spec:
- if a newly created child would otherwise be hidden, the parent should expand or the UI should clearly reveal the new child

---

## 16. Focus and persistence guarantees
Any structural navigation action should guarantee:
- no silent loss of edits
- deterministic focus target
- visible caret after movement
- preserved outline consistency

---

## 17. Summary of key behaviors

### Enter
- Create new node
- Usually next sibling
- Move focus into new node

### Shift+Enter
- Insert newline inside current node
- Stay in same node

### Tab
- Indent current node
- Make it a child of previous valid sibling

### ArrowUp
- Move within text
- At top boundary, move to previous visible node

### ArrowDown
- Move within text
- At bottom boundary, move to next visible node

### ArrowLeft
- Move left in text
- At left boundary, may trigger structural/editor-state transition

### ArrowRight
- Move right in text
- At right boundary, may trigger structural/editor-state transition

---

If you want, I can turn this into a cleaner **product-style functional spec** with sections like:
- **User stories**
- **Acceptance criteria**
- **Edge cases**
- **State transitions**