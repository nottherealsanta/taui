"""
taui.lsp — Language Server Protocol client manager.

Manages per-language LSP server subprocesses and provides
high-level operations: go-to-definition, references, hover,
document/workspace symbols, diagnostics, and call hierarchy.

Each language gets its own subprocess. Servers are started on
first use and shared across subsequent requests for that language.
"""

from taui.lsp.client import LspClient, LspError
from taui.lsp.manager import LspManager
from taui.lsp.types import (
    Diagnostic,
    HoverResult,
    Location,
    Position,
    Range,
    SymbolInfo,
)

__all__ = [
    "Diagnostic",
    "HoverResult",
    "Location",
    "LspClient",
    "LspError",
    "LspManager",
    "Position",
    "Range",
    "SymbolInfo",
]
