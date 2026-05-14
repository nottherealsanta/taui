"""
taui.symbols — workspace code index.

**Experimental — scaffolding for future symbol-aware tools.** No
built-in tool currently consumes ``SymbolIndexer``; ``Session``
constructs one but nothing reads from it. Subject to change or removal.

Provides AST-based symbol extraction for Python files.
No external dependencies (uses stdlib ``ast``).
"""

from taui.symbols.indexer import SymbolIndexer
from taui.symbols.models import SymbolEntry

__all__ = ["SymbolEntry", "SymbolIndexer"]
