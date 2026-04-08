"""Semantic reference resolver — resolves SemanticRef to ResolvedRef."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from .db import SymbolDB
from .models import ResolvedRef, SemanticRef, SymbolEntry

logger = logging.getLogger(__name__)

# Patterns for detecting safe-to-edit value shapes
_PYTHON_LITERAL_RE = re.compile(
    r"""^(?:
        -?\d+(?:\.\d+)?           # numeric
        | True | False | None     # boolean/None
        | "(?:[^"\\]|\\.)*"       # double-quoted string
        | '(?:[^'\\]|\\.)*'       # single-quoted string
        | \[.*\]                  # list literal
        | \{.*\}                  # dict/set literal
        | \(.*\)                  # tuple literal
    )$""",
    re.VERBOSE | re.DOTALL,
)

_JS_LITERAL_RE = re.compile(
    r"""^(?:
        -?\d+(?:\.\d+)?           # numeric
        | true | false | null | undefined
        | "(?:[^"\\]|\\.)*"       # double-quoted string
        | '(?:[^'\\]|\\.)*'       # single-quoted string
        | `(?:[^`\\]|\\.)*`       # template literal
    )$""",
    re.VERBOSE | re.DOTALL,
)


class SymbolResolver:
    """Resolves semantic references to concrete code locations."""

    def __init__(self, project_root: Path, symbol_db: SymbolDB) -> None:
        self.project_root = project_root.resolve()
        self.symbol_db = symbol_db

    async def resolve(self, ref: SemanticRef) -> ResolvedRef:
        """Resolve a SemanticRef to a ResolvedRef with diagnostics."""

        # file_ref: just check the file exists
        if ref.ref_kind == "file_ref":
            return self._resolve_file_ref(ref)

        # line_ref: resolve to specific lines
        if ref.ref_kind == "line_ref":
            return self._resolve_line_ref(ref)

        # symbol_ref or variable_ref: use symbol index
        if ref.ref_kind in ("symbol_ref", "variable_ref"):
            return await self._resolve_symbol_ref(ref)

        return ResolvedRef(
            file_path=ref.file_path,
            line_start=ref.line_start or 1,
            line_end=ref.line_end or 1,
            diagnostic="unresolved",
            fallback_reason=f"Unknown ref_kind: {ref.ref_kind}",
            confidence="low",
        )

    def _resolve_file_ref(self, ref: SemanticRef) -> ResolvedRef:
        """Resolve a file reference."""
        file_path = self.project_root / ref.file_path
        if not file_path.exists():
            return ResolvedRef(
                file_path=ref.file_path,
                line_start=1,
                line_end=1,
                diagnostic="unresolved",
                fallback_reason="File not found",
                confidence="low",
            )

        try:
            content = file_path.read_text(encoding="utf-8")
            lines = content.splitlines()
            # Show first 10 lines as preview
            preview = "\n".join(lines[:10])
            if len(lines) > 10:
                preview += f"\n... ({len(lines)} lines total)"
        except OSError:
            preview = ""
            lines = []

        return ResolvedRef(
            file_path=ref.file_path,
            line_start=1,
            line_end=len(lines) or 1,
            preview_snippet=preview,
            diagnostic="resolved",
            confidence="high",
        )

    def _resolve_line_ref(self, ref: SemanticRef) -> ResolvedRef:
        """Resolve a line range reference."""
        file_path = self.project_root / ref.file_path
        if not file_path.exists():
            return ResolvedRef(
                file_path=ref.file_path,
                line_start=ref.line_start or 1,
                line_end=ref.line_end or 1,
                diagnostic="unresolved",
                fallback_reason="File not found",
                confidence="low",
            )

        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError:
            return ResolvedRef(
                file_path=ref.file_path,
                line_start=ref.line_start or 1,
                line_end=ref.line_end or 1,
                diagnostic="unresolved",
                fallback_reason="Cannot read file",
                confidence="low",
            )

        lines = content.splitlines()
        ls = max(1, ref.line_start or 1)
        le = min(len(lines), ref.line_end or len(lines))
        preview = "\n".join(lines[ls - 1 : le])

        return ResolvedRef(
            file_path=ref.file_path,
            line_start=ls,
            line_end=le,
            preview_snippet=preview,
            diagnostic="resolved",
            confidence="high",
        )

    async def _resolve_symbol_ref(self, ref: SemanticRef) -> ResolvedRef:
        """Resolve a symbol or variable reference using the symbol index."""
        if not ref.symbol_path:
            return ResolvedRef(
                file_path=ref.file_path,
                line_start=1,
                line_end=1,
                diagnostic="unresolved",
                fallback_reason="No symbol_path specified",
                confidence="low",
            )

        # Parse symbol path: could be "ClassName.method_name" or just "func_name"
        parts = ref.symbol_path.split(".")
        symbol_name = parts[-1]

        # Try exact match in the specified file first
        symbol = await self.symbol_db.get_symbol(ref.file_path, symbol_name)

        if symbol is None:
            # Try all files
            candidates = await self.symbol_db.get_symbols_by_name(symbol_name)

            # Filter by file_path if specified and not empty
            if ref.file_path and candidates:
                file_matches = [c for c in candidates if c.file_path == ref.file_path]
                if file_matches:
                    candidates = file_matches

            # Filter by parent if we have a dotted path
            if len(parts) > 1 and candidates:
                parent_name = parts[-2]
                parent_matches = [
                    c for c in candidates if c.parent_symbol == parent_name
                ]
                if parent_matches:
                    candidates = parent_matches

            if not candidates:
                return ResolvedRef(
                    file_path=ref.file_path,
                    line_start=ref.line_start or 1,
                    line_end=ref.line_end or 1,
                    diagnostic="unresolved",
                    fallback_reason=f"Symbol '{ref.symbol_path}' not found",
                    confidence="low",
                )

            if len(candidates) > 1:
                # Ambiguous — return the first but mark it
                symbol = candidates[0]
                return self._build_resolved_from_symbol(
                    symbol,
                    ref,
                    diagnostic="ambiguous",
                    confidence="medium",
                    fallback_reason=f"{len(candidates)} candidates found",
                )

            symbol = candidates[0]

        # Check for staleness
        file_path = self.project_root / symbol.file_path
        diagnostic = "resolved"
        confidence = "high"
        fallback_reason = None

        if file_path.exists():
            try:
                from hashlib import sha256
                current_hash = sha256(file_path.read_bytes()).hexdigest()[:16]
                if current_hash != symbol.content_hash:
                    diagnostic = "stale"
                    confidence = "medium"
                    fallback_reason = "File has changed since last index"
            except OSError:
                diagnostic = "resolved_warning"
                confidence = "medium"
                fallback_reason = "Could not verify file hash"
        else:
            diagnostic = "unresolved"
            confidence = "low"
            fallback_reason = "File no longer exists"

        return self._build_resolved_from_symbol(
            symbol, ref, diagnostic=diagnostic,
            confidence=confidence, fallback_reason=fallback_reason,
        )

    def _build_resolved_from_symbol(
        self,
        symbol: SymbolEntry,
        ref: SemanticRef,
        *,
        diagnostic: str = "resolved",
        confidence: str = "high",
        fallback_reason: str | None = None,
    ) -> ResolvedRef:
        """Build a ResolvedRef from a SymbolEntry."""
        # Read preview
        preview = ""
        file_path = self.project_root / symbol.file_path
        if file_path.exists():
            try:
                lines = file_path.read_text(encoding="utf-8").splitlines()
                start = max(0, symbol.line_start - 1)
                end = min(len(lines), symbol.line_end)
                preview_lines = lines[start:end]
                if len(preview_lines) > 15:
                    preview = "\n".join(preview_lines[:15]) + f"\n... ({end - start} lines total)"
                else:
                    preview = "\n".join(preview_lines)
            except OSError:
                pass

        # Determine editability
        writable = False
        edit_strategy = None
        if ref.ref_kind == "variable_ref" and diagnostic in ("resolved", "resolved_warning"):
            writable, edit_strategy = self._assess_editability(symbol)

        return ResolvedRef(
            file_path=symbol.file_path,
            line_start=symbol.line_start,
            line_end=symbol.line_end,
            preview_snippet=preview,
            symbol_kind=symbol.kind,
            symbol_metadata={
                "name": symbol.name,
                "scope": symbol.scope,
                "parent": symbol.parent_symbol,
                "value_preview": symbol.value_preview,
            },
            writable=writable,
            edit_strategy=edit_strategy,
            confidence=confidence,
            fallback_reason=fallback_reason,
            diagnostic=diagnostic,
        )

    def _assess_editability(
        self, symbol: SymbolEntry
    ) -> tuple[bool, str | None]:
        """Determine if a symbol is safely editable and what strategy to use."""
        # Only variables and constants can be edited
        if symbol.kind not in ("variable", "constant", "css_property"):
            return False, None

        # CSS custom properties are always editable
        if symbol.kind == "css_property":
            return True, "replace_property"

        # Check if the value is a simple literal
        if symbol.value_preview is None:
            return False, None

        value = symbol.value_preview.strip()

        if symbol.language == "python":
            if _PYTHON_LITERAL_RE.match(value):
                return True, "replace_literal"
        elif symbol.language in ("typescript", "javascript"):
            if _JS_LITERAL_RE.match(value):
                return True, "replace_literal"
        elif symbol.language == "rust":
            # Rust const with simple literal
            if _PYTHON_LITERAL_RE.match(value):  # numeric/string patterns overlap
                return True, "replace_literal"

        return False, None

    async def update_value(
        self, file_path: str, symbol_name: str, new_value: str
    ) -> dict[str, Any]:
        """Update a writable variable's value in the source file.

        Returns dict with success, old_value, new_value, line.
        """
        symbol = await self.symbol_db.get_symbol(file_path, symbol_name)
        if symbol is None:
            return {"success": False, "error": f"Symbol '{symbol_name}' not found in {file_path}"}

        writable, edit_strategy = self._assess_editability(symbol)
        if not writable:
            return {
                "success": False,
                "error": f"Symbol '{symbol_name}' is not writable",
                "reason": "No safe edit strategy available",
            }

        abs_path = self.project_root / file_path
        if not abs_path.exists():
            return {"success": False, "error": f"File not found: {file_path}"}

        try:
            content = abs_path.read_text(encoding="utf-8")
        except OSError as exc:
            return {"success": False, "error": str(exc)}

        lines = content.splitlines(keepends=True)
        line_idx = symbol.line_start - 1

        if line_idx < 0 or line_idx >= len(lines):
            return {"success": False, "error": "Symbol line out of range"}

        line = lines[line_idx]
        old_value = symbol.value_preview

        if edit_strategy == "replace_literal":
            new_line = self._replace_literal_in_line(
                line, symbol_name, old_value, new_value, symbol.language
            )
        elif edit_strategy == "replace_property":
            new_line = self._replace_css_property(
                line, symbol.name, new_value
            )
        else:
            return {"success": False, "error": f"Unknown edit strategy: {edit_strategy}"}

        if new_line is None:
            return {
                "success": False,
                "error": "Could not locate value in source line",
            }

        lines[line_idx] = new_line
        abs_path.write_text("".join(lines), encoding="utf-8")

        return {
            "success": True,
            "old_value": old_value or "",
            "new_value": new_value,
            "line": symbol.line_start,
        }

    def _replace_literal_in_line(
        self,
        line: str,
        name: str,
        old_value: str | None,
        new_value: str,
        language: str,
    ) -> str | None:
        """Replace a literal value in an assignment line."""
        if old_value is None:
            return None

        # Find the old value in the line and replace it
        idx = line.find(old_value)
        if idx == -1:
            return None

        return line[:idx] + new_value + line[idx + len(old_value):]

    def _replace_css_property(
        self,
        line: str,
        prop_name: str,
        new_value: str,
    ) -> str | None:
        """Replace a CSS custom property value."""
        # Match: --prop-name: <value>;
        pattern = re.compile(
            rf"({re.escape(prop_name)}\s*:\s*)([^;]+)(;?)",
        )
        match = pattern.search(line)
        if not match:
            return None
        return line[: match.start(2)] + new_value + line[match.end(2):]
