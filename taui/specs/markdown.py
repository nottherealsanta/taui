from __future__ import annotations

from dataclasses import dataclass
import re

STATUS_RE = re.compile(r"\{\{status:\s*([a-zA-Z0-9_ -]+)\}\}")
ORDERED_LIST_RE = re.compile(r"^\d+\.\s+")


@dataclass(slots=True)
class Heading:
    level: int
    title: str
    line_index: int


def slugify(value: str) -> str:
    out: list[str] = []
    prev_dash = False
    for char in value:
        if char.isascii() and char.isalnum():
            out.append(char.lower())
            prev_dash = False
            continue
        if not prev_dash:
            out.append("-")
            prev_dash = True
    slug = "".join(out).strip("-")
    return slug or "untitled"


def parse_markdown_link(line: str) -> tuple[str, str] | None:
    start = line.find("[")
    if start < 0:
        return None
    rest = line[start + 1 :]
    text_end = rest.find("](")
    if text_end < 0:
        return None
    text = rest[:text_end]
    target_rest = rest[text_end + 2 :]
    target_end = target_rest.find(")")
    if target_end < 0:
        return None
    target = target_rest[:target_end]
    return text, target


def extract_headings(lines: list[str]) -> list[Heading]:
    out: list[Heading] = []
    for line_number, line in enumerate(lines):
        trimmed = line.lstrip()
        if not trimmed.startswith("#"):
            continue
        level = len(trimmed) - len(trimmed.lstrip("#"))
        if level <= 0:
            continue
        title = trimmed[level:].strip()
        if not title:
            continue
        out.append(Heading(level=level, title=title, line_index=line_number))
    return out


def extract_document_title_and_description(
    lines: list[str],
) -> tuple[str, str | None, int] | None:
    index = 0
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index >= len(lines):
        return None

    title = lines[index].strip()
    if title.startswith("#"):
        return None
    if parse_markdown_link(title) is not None:
        return None

    index += 1
    description: list[str] = []
    started = False
    while index < len(lines):
        raw_line = lines[index]
        line = raw_line.strip()
        if not line:
            if started:
                description.append("")
            index += 1
            continue
        if line.startswith("#"):
            break
        if parse_markdown_link(line) is not None:
            break
        description.append(line)
        started = True
        index += 1

    while description and not description[-1]:
        description.pop()

    intent = "\n".join(description) if description else None
    return title, intent, 0


def section_end_index(
    headings: list[Heading],
    heading_idx: int,
    total_lines: int,
    *,
    include_children: bool,
) -> int:
    current = headings[heading_idx]
    for later in headings[heading_idx + 1 :]:
        if include_children:
            if later.level <= current.level:
                return later.line_index
        elif later.level >= 1:
            return later.line_index
    return total_lines


def extract_status(lines: list[str], start: int, end: int) -> str | None:
    scan_end = min(end, start + 8)
    for idx in range(start, scan_end):
        match = STATUS_RE.search(lines[idx])
        if match:
            return match.group(1).strip()
    return None


def find_intent_line(lines: list[str], start: int, end: int) -> int | None:
    for idx in range(start, end):
        stripped = lines[idx].strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            return None
        if stripped.startswith(("- ", "* ", "+ ")):
            return None
        if ORDERED_LIST_RE.match(stripped):
            return None
        if stripped.startswith("[") and "](" in stripped:
            return None
        return idx
    return None


def extract_intent_text(lines: list[str], start: int, end: int) -> str | None:
    collected: list[str] = []
    started = False

    for idx in range(start, end):
        raw_line = lines[idx]
        stripped = lines[idx].strip()
        if not stripped:
            if started:
                collected.append("")
            continue
        if stripped.startswith("#"):
            break
        if stripped.startswith(("- ", "* ", "+ ")):
            break
        if ORDERED_LIST_RE.match(stripped):
            break
        if stripped.startswith("[") and "](" in stripped:
            break
        collected.append(raw_line.rstrip())
        started = True

    while collected and not collected[-1]:
        collected.pop()

    if not collected:
        return None
    return "\n".join(collected)
