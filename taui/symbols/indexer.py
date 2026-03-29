"""Tree-sitter based symbol indexer for Python, TypeScript, JavaScript, Rust, CSS."""

from __future__ import annotations

import logging
from hashlib import sha256
from pathlib import Path
from typing import Any

from .models import SymbolEntry

logger = logging.getLogger(__name__)

# File extensions → language mapping
EXTENSION_MAP: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".rs": "rust",
    ".css": "css",
}

# Directories to skip during scanning
SKIP_DIRS = frozenset({
    "node_modules", ".git", "__pycache__", ".venv", "venv",
    "target", "dist", "build", ".next", ".svelte-kit",
    ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "gen",
})

# File size limit for indexing (1 MB)
MAX_FILE_SIZE = 1_048_576


def _get_parser(language: str) -> Any:
    """Create a tree-sitter parser for the given language."""
    import tree_sitter

    lang_obj: Any = None
    if language == "python":
        import tree_sitter_python
        lang_obj = tree_sitter.Language(tree_sitter_python.language())
    elif language == "typescript":
        import tree_sitter_typescript
        lang_obj = tree_sitter.Language(tree_sitter_typescript.language_typescript())
    elif language == "javascript":
        import tree_sitter_javascript
        lang_obj = tree_sitter.Language(tree_sitter_javascript.language())
    elif language == "rust":
        import tree_sitter_rust
        lang_obj = tree_sitter.Language(tree_sitter_rust.language())
    elif language == "css":
        import tree_sitter_css
        lang_obj = tree_sitter.Language(tree_sitter_css.language())
    else:
        raise ValueError(f"Unsupported language: {language}")

    parser = tree_sitter.Parser(lang_obj)
    return parser


# Cache parsers per language
_parser_cache: dict[str, Any] = {}


def _get_cached_parser(language: str) -> Any:
    if language not in _parser_cache:
        _parser_cache[language] = _get_parser(language)
    return _parser_cache[language]


class SymbolIndexer:
    """Extracts symbols from source files using tree-sitter."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()

    def scan_project(self) -> list[SymbolEntry]:
        """Full scan of project, returning all extracted symbols."""
        symbols: list[SymbolEntry] = []
        for file_path in self._discover_files():
            try:
                file_symbols = self.index_file(file_path)
                symbols.extend(file_symbols)
            except Exception:
                logger.warning("Failed to index %s", file_path, exc_info=True)
        logger.info("Indexed %d symbols from project", len(symbols))
        return symbols

    def index_file(self, file_path: Path) -> list[SymbolEntry]:
        """Index a single file, returning extracted symbols."""
        rel_path = str(file_path.relative_to(self.project_root))
        ext = file_path.suffix.lower()
        language = EXTENSION_MAP.get(ext)
        if language is None:
            return []

        try:
            source = file_path.read_bytes()
        except OSError:
            return []

        if len(source) > MAX_FILE_SIZE:
            return []

        content_hash = sha256(source).hexdigest()[:16]
        parser = _get_cached_parser(language)
        tree = parser.parse(source)

        extractor = _EXTRACTORS.get(language)
        if extractor is None:
            return []

        return extractor(tree.root_node, rel_path, language, content_hash, source)

    def _discover_files(self) -> list[Path]:
        """Walk project tree and collect indexable files."""
        result: list[Path] = []
        stack: list[Path] = [self.project_root]
        while stack:
            directory = stack.pop()
            try:
                entries = sorted(directory.iterdir())
            except OSError:
                continue
            for entry in entries:
                if entry.is_dir():
                    if entry.name not in SKIP_DIRS:
                        stack.append(entry)
                elif entry.is_file() and entry.suffix.lower() in EXTENSION_MAP:
                    result.append(entry)
        return result


# ── Symbol ID generation ─────────────────────────────────────────────────────


def _make_id(file_path: str, name: str, kind: str, line: int) -> str:
    raw = f"{file_path}:{name}:{kind}:{line}"
    return sha256(raw.encode()).hexdigest()[:16]


# ── Value preview extraction ─────────────────────────────────────────────────


def _node_text(node: Any, source: bytes) -> str:
    """Extract text from a tree-sitter node."""
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _extract_value_preview(node: Any, source: bytes) -> str | None:
    """Try to extract a short value preview from a variable assignment."""
    text = _node_text(node, source)
    if len(text) > 100:
        return text[:97] + "..."
    return text if text else None


# ── Python extractor ─────────────────────────────────────────────────────────


def _extract_python(
    root: Any, file_path: str, language: str, content_hash: str, source: bytes
) -> list[SymbolEntry]:
    symbols: list[SymbolEntry] = []

    def _walk(node: Any, scope: str, parent_symbol: str | None) -> None:
        ntype = node.type

        if ntype == "function_definition":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, source)
                kind = "function"
                sym_scope = scope
                if scope.startswith("class:"):
                    kind = "function"  # method
                symbols.append(SymbolEntry(
                    id=_make_id(file_path, name, kind, node.start_point[0] + 1),
                    name=name,
                    kind=kind,
                    file_path=file_path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    scope=sym_scope,
                    parent_symbol=parent_symbol,
                    language=language,
                    content_hash=content_hash,
                ))
                # Recurse into function body
                body = node.child_by_field_name("body")
                if body:
                    for child in body.children:
                        _walk(child, f"function:{name}", name)
                return

        if ntype == "class_definition":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, source)
                symbols.append(SymbolEntry(
                    id=_make_id(file_path, name, "class", node.start_point[0] + 1),
                    name=name,
                    kind="class",
                    file_path=file_path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    scope=scope,
                    parent_symbol=parent_symbol,
                    language=language,
                    content_hash=content_hash,
                ))
                body = node.child_by_field_name("body")
                if body:
                    for child in body.children:
                        _walk(child, f"class:{name}", name)
                return

        if ntype == "expression_statement":
            # Look for assignments: NAME = value
            child = node.children[0] if node.children else None
            if child and child.type == "assignment":
                left = child.child_by_field_name("left")
                right = child.child_by_field_name("right")
                if left and left.type == "identifier" and right:
                    name = _node_text(left, source)
                    # Check if it looks like a constant (ALL_CAPS)
                    kind = "constant" if name.isupper() else "variable"
                    value_preview = _extract_value_preview(right, source)
                    symbols.append(SymbolEntry(
                        id=_make_id(file_path, name, kind, node.start_point[0] + 1),
                        name=name,
                        kind=kind,
                        file_path=file_path,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        scope=scope,
                        parent_symbol=parent_symbol,
                        language=language,
                        value_preview=value_preview,
                        content_hash=content_hash,
                    ))
                    return
                # Type-annotated assignment: NAME: type = value
            if child and child.type == "type_alias_statement":
                # type Foo = Bar
                name_node = child.child_by_field_name("name")
                if name_node:
                    name = _node_text(name_node, source)
                    symbols.append(SymbolEntry(
                        id=_make_id(file_path, name, "type", node.start_point[0] + 1),
                        name=name,
                        kind="type",
                        file_path=file_path,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        scope=scope,
                        parent_symbol=parent_symbol,
                        language=language,
                        content_hash=content_hash,
                    ))
                    return

        if ntype == "import_statement" or ntype == "import_from_statement":
            text = _node_text(node, source).strip()
            # Extract the module name
            if ntype == "import_from_statement":
                module = node.child_by_field_name("module_name")
                name = _node_text(module, source) if module else text
            else:
                name = text.removeprefix("import ").split(",")[0].strip().split(" ")[0]
            symbols.append(SymbolEntry(
                id=_make_id(file_path, name, "import", node.start_point[0] + 1),
                name=name,
                kind="import",
                file_path=file_path,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                scope=scope,
                parent_symbol=parent_symbol,
                language=language,
                content_hash=content_hash,
            ))
            return

        # Recurse into children
        for child in node.children:
            _walk(child, scope, parent_symbol)

    _walk(root, "module", None)
    return symbols


# ── TypeScript/JavaScript extractor ──────────────────────────────────────────


def _extract_ts_js(
    root: Any, file_path: str, language: str, content_hash: str, source: bytes
) -> list[SymbolEntry]:
    symbols: list[SymbolEntry] = []

    def _walk(node: Any, scope: str, parent_symbol: str | None) -> None:
        ntype = node.type

        # Function declarations
        if ntype in ("function_declaration", "generator_function_declaration"):
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, source)
                symbols.append(SymbolEntry(
                    id=_make_id(file_path, name, "function", node.start_point[0] + 1),
                    name=name,
                    kind="function",
                    file_path=file_path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    scope=scope,
                    parent_symbol=parent_symbol,
                    language=language,
                    content_hash=content_hash,
                ))
                body = node.child_by_field_name("body")
                if body:
                    for child in body.children:
                        _walk(child, f"function:{name}", name)
                return

        # Class declarations
        if ntype == "class_declaration":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, source)
                symbols.append(SymbolEntry(
                    id=_make_id(file_path, name, "class", node.start_point[0] + 1),
                    name=name,
                    kind="class",
                    file_path=file_path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    scope=scope,
                    parent_symbol=parent_symbol,
                    language=language,
                    content_hash=content_hash,
                ))
                body = node.child_by_field_name("body")
                if body:
                    for child in body.children:
                        _walk(child, f"class:{name}", name)
                return

        # Variable declarations (const/let/var)
        if ntype == "lexical_declaration" or ntype == "variable_declaration":
            for declarator in node.children:
                if declarator.type == "variable_declarator":
                    name_node = declarator.child_by_field_name("name")
                    value_node = declarator.child_by_field_name("value")
                    if name_node and name_node.type == "identifier":
                        name = _node_text(name_node, source)
                        # Arrow functions and function expressions
                        if value_node and value_node.type in (
                            "arrow_function", "function_expression", "function",
                        ):
                            symbols.append(SymbolEntry(
                                id=_make_id(file_path, name, "function", node.start_point[0] + 1),
                                name=name,
                                kind="function",
                                file_path=file_path,
                                line_start=node.start_point[0] + 1,
                                line_end=node.end_point[0] + 1,
                                scope=scope,
                                parent_symbol=parent_symbol,
                                language=language,
                                content_hash=content_hash,
                            ))
                        else:
                            # Check if const -> constant
                            is_const = any(
                                c.type == "const" for c in node.children
                                if hasattr(c, "type")
                            )
                            kind = "constant" if is_const and name.isupper() else "variable"
                            value_preview = _extract_value_preview(value_node, source) if value_node else None
                            symbols.append(SymbolEntry(
                                id=_make_id(file_path, name, kind, node.start_point[0] + 1),
                                name=name,
                                kind=kind,
                                file_path=file_path,
                                line_start=node.start_point[0] + 1,
                                line_end=node.end_point[0] + 1,
                                scope=scope,
                                parent_symbol=parent_symbol,
                                language=language,
                                value_preview=value_preview,
                                content_hash=content_hash,
                            ))
            return

        # Interface/type declarations (TypeScript)
        if ntype in ("interface_declaration", "type_alias_declaration"):
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, source)
                symbols.append(SymbolEntry(
                    id=_make_id(file_path, name, "type", node.start_point[0] + 1),
                    name=name,
                    kind="type",
                    file_path=file_path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    scope=scope,
                    parent_symbol=parent_symbol,
                    language=language,
                    content_hash=content_hash,
                ))
                return

        # Enum declarations (TypeScript)
        if ntype == "enum_declaration":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, source)
                symbols.append(SymbolEntry(
                    id=_make_id(file_path, name, "type", node.start_point[0] + 1),
                    name=name,
                    kind="type",
                    file_path=file_path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    scope=scope,
                    parent_symbol=parent_symbol,
                    language=language,
                    content_hash=content_hash,
                ))
                return

        # Export statements: unwrap and recurse into declaration
        if ntype == "export_statement":
            declaration = node.child_by_field_name("declaration")
            if declaration:
                _walk(declaration, scope, parent_symbol)
                return
            # Re-export or default export with value
            value = node.child_by_field_name("value")
            if value:
                _walk(value, scope, parent_symbol)
                return

        # Import statements
        if ntype == "import_statement":
            text = _node_text(node, source).strip()
            source_node = node.child_by_field_name("source")
            name = _node_text(source_node, source).strip("'\"") if source_node else text
            symbols.append(SymbolEntry(
                id=_make_id(file_path, name, "import", node.start_point[0] + 1),
                name=name,
                kind="import",
                file_path=file_path,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                scope=scope,
                parent_symbol=parent_symbol,
                language=language,
                content_hash=content_hash,
            ))
            return

        # Method definitions (in class body)
        if ntype == "method_definition":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, source)
                symbols.append(SymbolEntry(
                    id=_make_id(file_path, name, "function", node.start_point[0] + 1),
                    name=name,
                    kind="function",
                    file_path=file_path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    scope=scope,
                    parent_symbol=parent_symbol,
                    language=language,
                    content_hash=content_hash,
                ))
                return

        # Recurse
        for child in node.children:
            _walk(child, scope, parent_symbol)

    _walk(root, "module", None)
    return symbols


# ── Rust extractor ───────────────────────────────────────────────────────────


def _extract_rust(
    root: Any, file_path: str, language: str, content_hash: str, source: bytes
) -> list[SymbolEntry]:
    symbols: list[SymbolEntry] = []

    def _walk(node: Any, scope: str, parent_symbol: str | None) -> None:
        ntype = node.type

        if ntype == "function_item":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, source)
                symbols.append(SymbolEntry(
                    id=_make_id(file_path, name, "function", node.start_point[0] + 1),
                    name=name,
                    kind="function",
                    file_path=file_path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    scope=scope,
                    parent_symbol=parent_symbol,
                    language=language,
                    content_hash=content_hash,
                ))
                body = node.child_by_field_name("body")
                if body:
                    for child in body.children:
                        _walk(child, f"function:{name}", name)
                return

        if ntype in ("struct_item", "enum_item"):
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, source)
                kind = "class" if ntype == "struct_item" else "type"
                symbols.append(SymbolEntry(
                    id=_make_id(file_path, name, kind, node.start_point[0] + 1),
                    name=name,
                    kind=kind,
                    file_path=file_path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    scope=scope,
                    parent_symbol=parent_symbol,
                    language=language,
                    content_hash=content_hash,
                ))
                return

        if ntype == "impl_item":
            type_node = node.child_by_field_name("type")
            if type_node:
                type_name = _node_text(type_node, source)
                body = node.child_by_field_name("body")
                if body:
                    for child in body.children:
                        _walk(child, f"class:{type_name}", type_name)
            return

        if ntype == "trait_item":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, source)
                symbols.append(SymbolEntry(
                    id=_make_id(file_path, name, "type", node.start_point[0] + 1),
                    name=name,
                    kind="type",
                    file_path=file_path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    scope=scope,
                    parent_symbol=parent_symbol,
                    language=language,
                    content_hash=content_hash,
                ))
                body = node.child_by_field_name("body")
                if body:
                    for child in body.children:
                        _walk(child, f"class:{name}", name)
                return

        if ntype == "const_item" or ntype == "static_item":
            name_node = node.child_by_field_name("name")
            value_node = node.child_by_field_name("value")
            if name_node:
                name = _node_text(name_node, source)
                kind = "constant" if ntype == "const_item" else "variable"
                value_preview = _extract_value_preview(value_node, source) if value_node else None
                symbols.append(SymbolEntry(
                    id=_make_id(file_path, name, kind, node.start_point[0] + 1),
                    name=name,
                    kind=kind,
                    file_path=file_path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    scope=scope,
                    parent_symbol=parent_symbol,
                    language=language,
                    value_preview=value_preview,
                    content_hash=content_hash,
                ))
                return

        if ntype == "type_item":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, source)
                symbols.append(SymbolEntry(
                    id=_make_id(file_path, name, "type", node.start_point[0] + 1),
                    name=name,
                    kind="type",
                    file_path=file_path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    scope=scope,
                    parent_symbol=parent_symbol,
                    language=language,
                    content_hash=content_hash,
                ))
                return

        if ntype == "mod_item":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, source)
                body = node.child_by_field_name("body")
                if body:
                    for child in body.children:
                        _walk(child, f"module:{name}", name)
            return

        if ntype == "use_declaration":
            text = _node_text(node, source).strip()
            name = text.removeprefix("use ").rstrip(";").strip()
            symbols.append(SymbolEntry(
                id=_make_id(file_path, name, "import", node.start_point[0] + 1),
                name=name,
                kind="import",
                file_path=file_path,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                scope=scope,
                parent_symbol=parent_symbol,
                language=language,
                content_hash=content_hash,
            ))
            return

        for child in node.children:
            _walk(child, scope, parent_symbol)

    _walk(root, "module", None)
    return symbols


# ── CSS extractor ────────────────────────────────────────────────────────────


def _extract_css(
    root: Any, file_path: str, language: str, content_hash: str, source: bytes
) -> list[SymbolEntry]:
    symbols: list[SymbolEntry] = []

    def _walk(node: Any) -> None:
        ntype = node.type

        # CSS custom properties (--var-name: value)
        if ntype == "declaration":
            # In tree-sitter-css, declarations have children:
            # property_name, ":", <value_node>, ";"
            prop_node = None
            value_parts = []
            past_colon = False
            for child in node.children:
                if child.type == "property_name":
                    prop_node = child
                elif child.type == ":":
                    past_colon = True
                elif child.type == ";":
                    pass
                elif past_colon:
                    value_parts.append(child)

            if prop_node:
                prop_name = _node_text(prop_node, source)
                if prop_name.startswith("--"):
                    value_preview = None
                    if value_parts:
                        # Combine all value nodes for preview
                        start = value_parts[0].start_byte
                        end = value_parts[-1].end_byte
                        value_preview = source[start:end].decode("utf-8", errors="replace").strip()
                        if value_preview and len(value_preview) > 100:
                            value_preview = value_preview[:97] + "..."
                    symbols.append(SymbolEntry(
                        id=_make_id(file_path, prop_name, "css_property", node.start_point[0] + 1),
                        name=prop_name,
                        kind="css_property",
                        file_path=file_path,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        scope="module",
                        language=language,
                        value_preview=value_preview,
                        content_hash=content_hash,
                    ))

        for child in node.children:
            _walk(child)

    _walk(root)
    return symbols


# ── Extractor dispatch ───────────────────────────────────────────────────────

_EXTRACTORS = {
    "python": _extract_python,
    "typescript": _extract_ts_js,
    "javascript": _extract_ts_js,
    "rust": _extract_rust,
    "css": _extract_css,
}
