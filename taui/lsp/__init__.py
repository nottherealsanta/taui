"""
taui.lsp — Language Server Protocol client manager.

**Experimental — scaffolding for future LSP-aware tools.** No built-in
tool currently consumes this module; ``Session`` instantiates an
``LspManager`` only so it can be shut down cleanly. Subject to change
or removal.

Manages per-language LSP server subprocesses and provides
high-level operations: go-to-definition, references, hover,
document/workspace symbols, diagnostics, and call hierarchy.
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
