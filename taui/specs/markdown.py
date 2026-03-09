from __future__ import annotations

from dataclasses import dataclass
import re

STATUS_RE = re.compile(r"\{\{status:\s*([a-zA-Z0-9_ -]+)\}\}")
ORDERED_LIST_RE = re.compile(r"^\d+\.\s+")
LIST_ITEM_RE = re.compile(r"^( *)([-*+])\s+(.*\S)?\s*$")
WIKI_LINK_RE = re.compile(r"^\[\[([^\]]+)\]\]$")
INLINE_METADATA_RE = re.compile(r"\{\{[^}]+\}\}")


@dataclass(slots=True)
class Heading:
    level: int
    title: str
    line_index: int


@dataclass(slots=True)
class ListItem:
    depth: int
    title: str
    line_index: int
    parent_index: int | None
    content_lines: list[str]


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


def parse_wiki_link(value: str) -> str | None:
    match = WIKI_LINK_RE.match(value.strip())
    if match is None:
        return None
    target = match.group(1).strip()
    if not target:
        return None
    return target


def strip_inline_metadata(value: str) -> str:
    stripped = INLINE_METADATA_RE.sub("", value)
    return " ".join(stripped.split())


def markdown_first_line(markdown: str) -> str:
    if not markdown:
        return ""
    return markdown.splitlines()[0].strip()


def markdown_anchor_text(markdown: str) -> str:
    return strip_inline_metadata(markdown_first_line(markdown))


def parse_list_items(lines: list[str], *, indent_size: int = 4) -> list[ListItem]:
    items: list[ListItem] = []
    stack: list[int] = []
    current_idx: int | None = None

    for line_index, raw_line in enumerate(lines):
        match = LIST_ITEM_RE.match(raw_line)
        if match is not None:
            indent = len(match.group(1))
            if indent_size <= 0:
                depth = 0
            else:
                depth = indent // indent_size

            title = (match.group(3) or "").strip()
            while len(stack) > depth:
                stack.pop()

            parent_index = stack[-1] if stack else None
            items.append(
                ListItem(
                    depth=depth,
                    title=title,
                    line_index=line_index,
                    parent_index=parent_index,
                    content_lines=[],
                )
            )
            current_idx = len(items) - 1

            if len(stack) == depth:
                stack.append(current_idx)
            else:
                stack[depth] = current_idx
            continue

        if current_idx is None:
            continue

        current = items[current_idx]
        required_indent = (current.depth + 1) * indent_size
        if raw_line.strip() and len(raw_line) >= required_indent:
            content_line = raw_line[required_indent:]
        else:
            content_line = raw_line.strip()
        current.content_lines.append(content_line.rstrip())

    return items


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


def extract_status_from_block(title: str, lines: list[str]) -> str | None:
    title_match = STATUS_RE.search(title)
    if title_match:
        return title_match.group(1).strip()
    scan_end = min(8, len(lines))
    for line in lines[:scan_end]:
        match = STATUS_RE.search(line)
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
        if parse_wiki_link(stripped) is not None:
            return None
        if stripped.startswith("{{") and stripped.endswith("}}"):
            continue
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
        if parse_wiki_link(stripped) is not None:
            break
        if stripped.startswith("{{") and stripped.endswith("}}"):
            continue
        collected.append(raw_line.rstrip())
        started = True

    while collected and not collected[-1]:
        collected.pop()

    if not collected:
        return None
    return "\n".join(collected)
