from __future__ import annotations

import re

from .models import TangleRef


ARROW_RE = re.compile(r"(?:->|→)\s*([A-Za-z0-9_./\\-]+):([A-Za-z0-9_\\-]+)")
BACKTICK_RE = re.compile(r"`([A-Za-z0-9_./\\-]+):([A-Za-z0-9_\\-]+)`")


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
