from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

ORDERED_LIST_RE = re.compile(r"^\d+\.\s+")
LIST_ITEM_RE = re.compile(r"^( *)([-*+])\s+(.*\S)?\s*$")
INLINE_METADATA_RE = re.compile(r"\{\{[^}]+\}\}")


@dataclass(slots=True)
class Heading:
    level: int
    title: str
    line_index: int


@dataclass(slots=True)
class HeadingNode:
    level: int
    title: str
    line_index: int
    body_lines: list[str] = field(default_factory=list)
    parent_index: int | None = None


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


def parse_yaml_frontmatter(lines: list[str]) -> tuple[dict[str, Any], int]:
    """Parse YAML frontmatter from --- delimited block at top of file.

    Returns (metadata_dict, body_start_line_index).
    If no frontmatter found, returns ({}, 0).
    """
    if not lines or lines[0].strip() != "---":
        return {}, 0
    end: int | None = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, 0

    result: dict[str, Any] = {}
    current_key: str | None = None
    current_list: list[str] | None = None

    for line in lines[1:end]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # List item continuation
        if stripped.startswith("- ") and current_key is not None and current_list is not None:
            current_list.append(stripped[2:].strip())
            continue
        # Key-value pair
        if ":" in stripped:
            if current_key and current_list is not None:
                result[current_key] = current_list
                current_list = None
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()
            if value:
                result[key] = value
                current_key = key
            else:
                current_key = key
                current_list = []
            continue

    if current_key and current_list is not None:
        result[current_key] = current_list

    return result, end + 1


def parse_heading_tree(lines: list[str], start: int = 0) -> list[HeadingNode]:
    """Parse standard markdown headings into a tree structure.

    Returns a list of HeadingNode objects with parent_index set based on
    heading level relationships.
    """
    nodes: list[HeadingNode] = []
    # Stack holds (level, index_in_nodes)
    stack: list[tuple[int, int]] = []

    for line_index in range(start, len(lines)):
        raw = lines[line_index]
        stripped = raw.lstrip()
        if not stripped.startswith("#"):
            # Accumulate body into the most recent node
            if nodes:
                nodes[-1].body_lines.append(raw.rstrip())
            continue
        level = len(stripped) - len(stripped.lstrip("#"))
        if level <= 0:
            if nodes:
                nodes[-1].body_lines.append(raw.rstrip())
            continue
        title = stripped[level:].strip()
        if not title:
            if nodes:
                nodes[-1].body_lines.append(raw.rstrip())
            continue

        # Find parent: walk back the stack until we find a node with lower level
        while stack and stack[-1][0] >= level:
            stack.pop()
        parent_index = stack[-1][1] if stack else None

        node = HeadingNode(
            level=level,
            title=title,
            line_index=line_index,
            body_lines=[],
            parent_index=parent_index,
        )
        node_index = len(nodes)
        nodes.append(node)
        stack.append((level, node_index))

    # Strip trailing blank lines from each node's body
    for node in nodes:
        while node.body_lines and not node.body_lines[-1].strip():
            node.body_lines.pop()

    return nodes


def extract_metadata_from_frontmatter(fm: dict[str, Any]) -> dict[str, Any]:
    """Normalize frontmatter keys to the internal metadata format.

    Only title, status, and last_updated belong in frontmatter.
    code_refs, test_refs, depends_on, and domain belong in the note body.
    """
    return {
        "status": fm.get("status"),
        "title": fm.get("title"),
        "last_updated": fm.get("last_updated"),
    }


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
        if stripped.startswith("{{") and stripped.endswith("}}"):
            continue
        collected.append(raw_line.rstrip())
        started = True

    while collected and not collected[-1]:
        collected.pop()

    if not collected:
        return None
    return "\n".join(collected)
