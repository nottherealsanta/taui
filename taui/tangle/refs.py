from __future__ import annotations

import re

from .models import TangleRef, TangleCodeBlock


ARROW_RE = re.compile(r"(?:->|→)\s*([A-Za-z0-9_./\\-]+):([A-Za-z0-9_\\-]+)")
BACKTICK_RE = re.compile(r"`([A-Za-z0-9_./\\-]+):([A-Za-z0-9_\\-]+)`")

# ::code directive pattern
# Matches: ::code file/path.py:symbol_name or ::code file/path.py:10-25
CODE_BLOCK_RE = re.compile(r"^::code\s+([A-Za-z0-9_./\\-]+):([A-Za-z0-9_.-]+)\s*$")

# Pattern to detect if target is a line range (e.g., "10-25" or "10")
LINE_RANGE_RE = re.compile(r"^(\d+)(?:-(\d+))?$")


def extract_tangle_refs(lines: list[str]) -> list[TangleRef]:
    refs: list[TangleRef] = []
    for idx, line in enumerate(lines, start=1):
        for pattern in (ARROW_RE, BACKTICK_RE):
            for match in pattern.finditer(line):
                refs.append(
                    TangleRef(
                        file_path=match.group(1),
                        target=match.group(2),
                        context=line.strip(),
                        line_in_tangle=idx,
                    )
                )
    return refs


def extract_code_blocks(lines: list[str]) -> list[TangleCodeBlock]:
    """Extract ::code directives from tangle body lines.

    Format:
        ::code file/path.py:symbol_name
        ::code file/path.py:10-25
        ::code file/path.py:10

    Returns list of TangleCodeBlock with unresolved content (content=None).
    Resolution happens separately via the symbol resolver.
    """
    blocks: list[TangleCodeBlock] = []
    for idx, line in enumerate(lines, start=1):
        match = CODE_BLOCK_RE.match(line.strip())
        if not match:
            continue

        file_path = match.group(1)
        target = match.group(2)

        # Determine if target is a line range or symbol
        line_match = LINE_RANGE_RE.match(target)
        if line_match:
            ref_kind = "lines"
        else:
            ref_kind = "symbol"

        blocks.append(
            TangleCodeBlock(
                file_path=file_path,
                target=target,
                line_in_tangle=idx,
                ref_kind=ref_kind,
            )
        )

    return blocks
