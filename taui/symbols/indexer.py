"""AST-based symbol indexer for Python files.

Uses the stdlib ``ast`` module — no external dependencies.
Extracts functions, classes, methods, constants, and type aliases.
"""

from __future__ import annotations

import ast
import logging
from hashlib import sha256
from pathlib import Path

from .models import SymbolEntry

logger = logging.getLogger(__name__)

SKIP_DIRS = frozenset({
    "node_modules", ".git", "__pycache__", ".venv", "venv",
    "target", "dist", "build", ".next", ".svelte-kit",
    ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
})

MAX_FILE_SIZE = 1_048_576  # 1 MB


class SymbolIndexer:
    """Extracts Python symbols from source files using the stdlib ``ast`` module."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()

    def scan_project(self) -> list[SymbolEntry]:
        symbols: list[SymbolEntry] = []
        for file_path in self._discover_files():
            try:
                symbols.extend(self.index_file(file_path))
            except Exception:
                logger.warning("Failed to index %s", file_path, exc_info=True)
        logger.info("Indexed %d symbols from project", len(symbols))
        return symbols

    def index_file(self, file_path: Path) -> list[SymbolEntry]:
        rel_path = str(file_path.relative_to(self.project_root))
        if file_path.suffix != ".py":
            return []
        try:
            source = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        if len(source) > MAX_FILE_SIZE:
            return []

        content_hash = sha256(source.encode()).hexdigest()[:16]
        try:
            tree = ast.parse(source, filename=rel_path)
        except SyntaxError:
            return []

        symbols: list[SymbolEntry] = []
        self._walk(tree, rel_path, "module", None, content_hash, symbols)
        return symbols

    # ------------------------------------------------------------------

    def _walk(
        self,
        node: ast.AST,
        file_path: str,
        scope: str,
        parent: str | None,
        content_hash: str,
        out: list[SymbolEntry],
    ) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                kind = "method" if scope.startswith("class:") else "function"
                sym = self._make(
                    child.name, kind, file_path, child, scope, parent, content_hash,
                )
                out.append(sym)
                child_scope = f"function:{child.name}"
                self._walk(child, file_path, child_scope, child.name, content_hash, out)
            elif isinstance(child, ast.ClassDef):
                sym = self._make(
                    child.name, "class", file_path, child, scope, parent, content_hash,
                )
                out.append(sym)
                child_scope = f"class:{child.name}"
                self._walk(child, file_path, child_scope, child.name, content_hash, out)
            elif isinstance(child, ast.Assign):
                self._handle_assign(child, file_path, scope, parent, content_hash, out)
            elif isinstance(child, ast.AnnAssign) and child.target:
                if isinstance(child.target, ast.Name):
                    kind = self._classify_var(child.target.id, scope)
                    preview = ast.unparse(child.value) if child.value else None
                    sym = self._make(
                        child.target.id, kind, file_path, child, scope, parent,
                        content_hash, preview,
                    )
                    out.append(sym)

    def _handle_assign(
        self,
        node: ast.Assign,
        file_path: str,
        scope: str,
        parent: str | None,
        content_hash: str,
        out: list[SymbolEntry],
    ) -> None:
        preview = ast.unparse(node.value) if node.value else None
        for target in node.targets:
            if isinstance(target, ast.Name):
                kind = self._classify_var(target.id, scope)
                sym = self._make(
                    target.id, kind, file_path, node, scope, parent,
                    content_hash, preview,
                )
                out.append(sym)

    @staticmethod
    def _classify_var(name: str, scope: str) -> str:
        if name.isupper() and scope == "module":
            return "constant"
        return "variable"

    def _make(
        self,
        name: str,
        kind: str,
        file_path: str,
        node: ast.AST,
        scope: str,
        parent: str | None,
        content_hash: str,
        preview: str | None = None,
    ) -> SymbolEntry:
        line_start = getattr(node, "lineno", 1)
        line_end = getattr(node, "end_lineno", line_start) or line_start
        sym_id = f"{file_path}::{scope}::{name}"
        if preview and len(preview) > 120:
            preview = preview[:117] + "..."
        return SymbolEntry(
            id=sym_id,
            name=name,
            kind=kind,
            file_path=file_path,
            line_start=line_start,
            line_end=line_end,
            scope=scope,
            parent_symbol=parent,
            language="python",
            value_preview=preview,
            content_hash=content_hash,
        )

    def _discover_files(self) -> list[Path]:
        files: list[Path] = []
        for item in self.project_root.rglob("*.py"):
            if any(p in SKIP_DIRS for p in item.parts):
                continue
            if item.stat().st_size > MAX_FILE_SIZE:
                continue
            files.append(item)
        files.sort()
        return files
