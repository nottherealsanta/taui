"""
taui.symbols — workspace code index.

Provides AST-based symbol extraction for Python files.
No external dependencies (uses stdlib ``ast``).
"""

from taui.symbols.indexer import SymbolIndexer
from taui.symbols.models import SymbolEntry

__all__ = ["SymbolEntry", "SymbolIndexer"]
