"""Build a context tree of messages for inspection in the UI."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.widgets import Tree

from taui.agent.context import estimate_message_tokens, estimate_total_tokens

ROLE_STYLES = {
    "system": "#d2a8ff",
    "tool def": "#56d4dd",
    "user": "#7ee787",
    "assistant": "#58a6ff",
    "tool": "#ffa657",
}


def build_context_tree(messages: list[Any], max_tokens: int) -> Tree[str]:
    """Return a Tree summarising message-by-message context usage."""
    total_tokens = estimate_total_tokens(messages)
    pct = (total_tokens / max_tokens * 100) if max_tokens else 0.0
    tree: Tree[str] = Tree(
        f"Context {total_tokens:,}/{max_tokens:,} tokens ({pct:.1f}%)",
        classes="context-tree",
    )
    tree.root.expand()

    current_user = None
    current_reply = None
    user_count = 0
    for message in messages:
        role = str(getattr(message, "role", "unknown") or "unknown")
        content = _message_content(message)
        if role == "system":
            system_content, tool_def_content = _split_system_tool_def(content)
            if system_content:
                system_tokens = _estimate_text_tokens("system", system_content)
                system_node = tree.root.add(
                    _context_message_label("system", system_tokens, user_count),
                    expand=False,
                )
                _add_context_message_details(system_node, message, system_content)
            if tool_def_content:
                tool_def_tokens = _estimate_text_tokens("tool def", tool_def_content)
                tool_def_node = tree.root.add(
                    _context_message_label("tool def", tool_def_tokens, user_count),
                    expand=False,
                )
                _add_context_message_details(
                    tool_def_node, message, tool_def_content
                )
            continue
        if role == "user":
            user_count += 1
        message_tokens = estimate_message_tokens(message)
        label = _context_message_label(role, message_tokens, user_count)
        if role == "user":
            current_user = tree.root.add(label, expand=False)
            current_reply = None
            _add_context_message_details(current_user, message, content)
            continue
        if role == "assistant":
            parent = current_user or tree.root
            current_reply = parent.add(label, expand=False)
            _add_context_message_details(current_reply, message, content)
            continue
        if role == "tool":
            parent = current_reply or current_user or tree.root
        else:
            parent = tree.root
        group = parent.add(label, expand=False)
        _add_context_message_details(group, message, content)
    return tree


def _message_content(message: Any) -> str:
    content = getattr(message, "content", None) or ""
    if not content and getattr(message, "tool_calls", None):
        names = [
            str(getattr(call, "name", "tool"))
            for call in (getattr(message, "tool_calls", None) or [])
        ]
        content = "tool calls: " + ", ".join(names)
    if not content and getattr(message, "name", None):
        content = str(getattr(message, "name"))
    return str(content) or "(empty)"


def _split_system_tool_def(content: str) -> tuple[str, str]:
    marker = "# Available tools"
    start = content.find(marker)
    if start < 0:
        return content, ""
    next_header = content.find("\n# ", start + len(marker))
    if next_header < 0:
        system_content = content[:start].rstrip()
        tool_def_content = content[start:].strip()
    else:
        system_content = (content[:start] + content[next_header:]).strip()
        tool_def_content = content[start:next_header].strip()
    return system_content, tool_def_content


def _estimate_text_tokens(role: str, content: str) -> int:
    return max(1, (len(role) + len(content)) // 4 + 1)


def _context_message_label(role: str, message_tokens: int, user_count: int) -> Text:
    text = Text()
    if role == "user":
        text.append(f"user {user_count}", style=f"bold {ROLE_STYLES['user']}")
    else:
        text.append(role, style=f"bold {ROLE_STYLES.get(role, '#c9d1d9')}")
    text.append(f"  {message_tokens:,}t", style="italic dim")
    return text


def _add_context_message_details(node: Any, message: Any, content: str) -> None:
    content_node = node.add(Text("content", style="dim"), expand=True)
    for line in content.splitlines() or [content]:
        content_node.add_leaf(Text(line if line else " ", style="#c9d1d9"))
    if getattr(message, "name", None):
        node.add_leaf(Text(f"name: {getattr(message, 'name')}", style="dim"))
    if getattr(message, "tool_call_id", None):
        node.add_leaf(
            Text(f"tool_call_id: {getattr(message, 'tool_call_id')}", style="dim")
        )
    for call in getattr(message, "tool_calls", None) or []:
        name = str(getattr(call, "name", "tool"))
        call_id = str(getattr(call, "call_id", ""))
        node.add_leaf(
            Text(f"tool_call: {name} {call_id}".rstrip(), style="#ffa657")
        )
