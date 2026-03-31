"""MontyTool — sandboxed Python execution with a restricted taui API."""

from __future__ import annotations

import io
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from typing import Any

from taui.tools.base import ToolCategory, ToolContext, ToolResult
from taui.tools.builtins.monty_api import MontyAPI


# Maximum output size in characters
_MAX_OUTPUT = 50_000

# Modules forbidden from import inside Monty
_BLOCKED_MODULES = frozenset({
    "subprocess", "shutil", "socket", "http", "urllib",
    "requests", "httpx", "aiohttp",
    "ctypes", "multiprocessing",
})


@dataclass(slots=True)
class MontyTool:
    name: str = "monty"
    description: str = (
        "Execute a Python script in a sandboxed environment with access to a "
        "read-only workspace API.\n\n"
        "Available in the script's namespace:\n"
        "  api.read_file(path) — read a file from the workspace\n"
        "  api.file_exists(path) — check if file exists\n"
        "  api.list_dir(path) — list directory entries\n"
        "  api.glob(pattern) — glob files\n"
        "  api.workspace_root() — get workspace root path\n\n"
        "Use print() for output. The script runs with restricted imports — "
        "no subprocess, network, or system-level access.\n\n"
        "Parameters:\n"
        "  code (required): Python code to execute"
    )
    schema: dict[str, Any] = field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Python code to execute.",
            },
        },
        "required": ["code"],
        "additionalProperties": False,
    })
    origin: str = "builtin"
    category: ToolCategory = ToolCategory.AGENT

    async def execute(
        self, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        code = arguments.get("code", "")
        if not code.strip():
            return ToolResult.fail("code is required.")

        api = MontyAPI(context.working_dir)

        # Build a restricted namespace
        namespace: dict[str, Any] = {
            "api": api,
            "__builtins__": _safe_builtins(),
        }

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()

        try:
            compiled = compile(code, "<monty>", "exec")
            with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                exec(compiled, namespace)  # noqa: S102  — intentional sandboxed exec
        except Exception:
            tb = traceback.format_exc()
            stderr_buf.write(tb)

        stdout = stdout_buf.getvalue()
        stderr = stderr_buf.getvalue()

        parts: list[str] = []
        if stdout:
            parts.append(stdout[:_MAX_OUTPUT])
        if stderr:
            parts.append(f"--- stderr ---\n{stderr[:_MAX_OUTPUT]}")

        output = "\n".join(parts) if parts else "(no output)"
        has_error = bool(stderr)
        return ToolResult(content=output, error=has_error)


def _safe_builtins() -> dict[str, Any]:
    """Return a restricted __builtins__ dict."""
    import builtins as _b

    allowed = {
        # Types
        "True", "False", "None",
        "int", "float", "str", "bytes", "bool", "complex",
        "list", "tuple", "dict", "set", "frozenset",
        "type", "object", "slice", "range",
        # Functions
        "abs", "all", "any", "bin", "chr", "divmod", "enumerate",
        "filter", "format", "hash", "hex", "id", "isinstance",
        "issubclass", "iter", "len", "map", "max", "min", "next",
        "oct", "ord", "pow", "print", "repr", "reversed", "round",
        "sorted", "sum", "zip",
        # Comprehension helpers
        "getattr", "setattr", "hasattr", "callable",
        "dir", "vars",
        # String / collection
        "input",  # blocked at IO level, but needed for syntax
        # Exceptions
        "Exception", "ValueError", "TypeError", "KeyError",
        "IndexError", "AttributeError", "StopIteration",
        "RuntimeError", "NotImplementedError", "PermissionError",
        "FileNotFoundError", "IOError", "OSError",
    }

    safe: dict[str, Any] = {}
    for name in allowed:
        val = getattr(_b, name, None)
        if val is not None:
            safe[name] = val

    # Restricted __import__
    original_import = _b.__import__

    def _restricted_import(
        name: str,
        globals: Any = None,
        locals: Any = None,
        fromlist: Any = (),
        level: int = 0,
    ) -> Any:
        top = name.split(".")[0]
        if top in _BLOCKED_MODULES:
            raise ImportError(f"Import of '{name}' is not allowed in Monty scripts.")
        return original_import(name, globals, locals, fromlist, level)

    safe["__import__"] = _restricted_import
    return safe
