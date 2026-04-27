# Symbols

AST-based workspace symbol indexer. Extracts functions, classes, methods, constants, and variables from Python source files using the stdlib `ast` module — no external dependencies.

---

## Architecture

```
SymbolIndexer(project_root)
  │
  ├── scan_project()       → walk all .py files, return SymbolEntry list
  ├── index_file(path)     → parse single file, return entries
  │
  └── Internal:
      ├── _discover_files()  → rglob *.py, skip dirs, size limit
      ├── _walk(node)        → recursive AST visitor
      ├── _handle_assign()   → extract assignments
      └── _classify_var()    → constant vs variable
              │
              ▼
SymbolEntry (dataclass)
  │
  ├── id           → "file::scope::name" unique identifier
  ├── name         → symbol name
  ├── kind         → function | class | method | variable | constant
  ├── file_path    → relative to project root
  ├── line_start   → 1-based
  ├── line_end     → 1-based, inclusive
  ├── scope        → "module" | "class:Name" | "function:name"
  ├── parent_symbol → containing class/function name
  ├── language     → always "python" (for now)
  ├── value_preview → first 120 chars of assigned value
  └── content_hash → SHA-256 prefix of file content
```

---

## Usage

```python
from taui.symbols import SymbolIndexer

idx = SymbolIndexer(Path("/my/project"))
symbols = idx.scan_project()

for sym in symbols:
    print(f"{sym.kind:10} {sym.name:30} {sym.file_path}:{sym.line_start}")
```

### Index a Single File

```python
entries = idx.index_file(Path("/my/project/src/main.py"))
```

---

## Symbol Kinds

| Kind | Detected From | Scope Rule |
|------|---------------|------------|
| `function` | `def`, `async def` at module or function scope | `scope != "class:*"` |
| `method` | `def`, `async def` inside a class | `scope.startswith("class:")` |
| `class` | `class` statement | any scope |
| `constant` | Assignment with `UPPER_CASE` name at module scope | `name.isupper() and scope == "module"` |
| `variable` | Any other assignment | default |

---

## Scoping

Symbols track their lexical scope:

```python
# scope: "module"
MAX_SIZE = 1024          # constant, scope="module"

class Parser:            # class, scope="module"
    # scope: "class:Parser"
    def parse(self):     # method, scope="class:Parser", parent="Parser"
        # scope: "function:parse"
        result = []      # variable, scope="function:parse", parent="parse"
```

---

## Skip Directories

The indexer skips common non-source directories:

```
node_modules, .git, __pycache__, .venv, venv,
target, dist, build, .next, .svelte-kit,
.tox, .mypy_cache, .pytest_cache, .ruff_cache
```

Files larger than 1 MB are also skipped.

---

## Content Hashing

Each file's content is hashed (SHA-256, first 16 hex chars). This enables incremental re-indexing — if the hash matches, the file hasn't changed.

```python
content_hash = sha256(source.encode()).hexdigest()[:16]
```

---

## Symbol ID

Each symbol gets a unique identifier: `"{file_path}::{scope}::{name}"`.

```
src/parser.py::module::Parser
src/parser.py::class:Parser::parse
src/parser.py::function:parse::result
```

---

## Serialization

```python
entry = SymbolEntry(id="x", name="x", kind="function", ...)
d = entry.to_dict()           # dict with all fields
entry2 = SymbolEntry.from_dict(d)  # roundtrip
```

---

## Value Preview

Assigned values are stored as a preview (truncated to 120 chars):

```python
MAX_SIZE = 1024           # value_preview = "1024"
name: str = 'hello'       # value_preview = "'hello'"
BIG = "a" * 200           # value_preview = "'aaa...'" (truncated)
```

---

## Module Layout

```
taui/symbols/
├── __init__.py     # public exports: SymbolIndexer, SymbolEntry
├── indexer.py      # SymbolIndexer with AST-based extraction
└── models.py       # SymbolEntry dataclass
```
