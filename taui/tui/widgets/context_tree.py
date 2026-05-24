"""Build a context tree of messages for inspection in the UI."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.widgets import Tree
from textual.widgets.tree import TreeNode

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

    current_user: TreeNode | None = None
    current_user_tokens: int = 0
    current_user_preview: str = ""
    current_reply: TreeNode | None = None
    current_reply_tokens: int = 0

    def _finalize_user() -> None:
        if current_user is None:
            return
        current_user.set_label(
            _user_message_label(current_user_preview, current_user_tokens)
        )

    def _finalize_reply() -> None:
        if current_reply is None:
            return
        current_reply.set_label(
            _context_message_label("assistant", current_reply_tokens)
        )

    for message in messages:
        role = str(getattr(message, "role", "unknown") or "unknown")
        content = _message_content(message)
        if role == "system":
            system_content, tool_def_content = _split_system_tool_def(content)
            if system_content:
                system_tokens = _estimate_text_tokens("system", system_content)
                system_node = tree.root.add(
                    _context_message_label("system", system_tokens),
                    expand=False,
                )
                _add_context_message_details(
                    system_node, message, system_content, system_tokens
                )
            if tool_def_content:
                tool_def_tokens = _estimate_text_tokens("tool def", tool_def_content)
                tool_def_node = tree.root.add(
                    _context_message_label("tool def", tool_def_tokens),
                    expand=False,
                )
                _add_context_message_details(
                    tool_def_node, message, tool_def_content, tool_def_tokens
                )
            continue
        message_tokens = estimate_message_tokens(message)
        if role == "user":
            _finalize_reply()
            current_reply = None
            current_reply_tokens = 0
            _finalize_user()
            current_user_preview = _user_preview(content)
            current_user_tokens = message_tokens
            current_user = tree.root.add(
                _user_message_label(current_user_preview, current_user_tokens),
                expand=False,
            )
            _add_context_message_details(
                current_user, message, content, message_tokens
            )
            continue
        if role == "assistant":
            _finalize_reply()
            parent = current_user or tree.root
            current_reply = parent.add(
                _context_message_label("assistant", message_tokens),
                expand=False,
            )
            current_reply_tokens = message_tokens
            _add_context_message_details(
                current_reply, message, content, message_tokens
            )
            if current_user is not None:
                current_user_tokens += message_tokens
            continue
        if role == "tool":
            parent = current_reply or current_user or tree.root
            if current_user is not None:
                current_user_tokens += message_tokens
            if current_reply is not None:
                current_reply_tokens += message_tokens
        else:
            parent = tree.root
        group = parent.add(
            _context_message_label(role, message_tokens), expand=False
        )
        _add_context_message_details(group, message, content, message_tokens)

    _finalize_reply()
    _finalize_user()
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


def _user_preview(content: str) -> str:
    """One-line preview of user content, trimmed to 30 chars."""
    first_line = next((line for line in content.splitlines() if line.strip()), content)
    first_line = first_line.strip()
    if len(first_line) > 30:
        first_line = first_line[:30]
    return first_line or "(empty)"


def _format_tokens(message_tokens: int) -> str:
    return f"[{message_tokens:,}]"


def _context_message_label(role: str, message_tokens: int) -> Text:
    text = Text()
    text.append(role, style=f"bold {ROLE_STYLES.get(role, '#c9d1d9')}")
    text.append(f"  {_format_tokens(message_tokens)}", style="italic dim")
    return text


def _user_message_label(preview: str, cumulative_tokens: int) -> Text:
    text = Text()
    text.append("user: ", style=f"bold {ROLE_STYLES['user']}")
    text.append(preview, style=ROLE_STYLES["user"])
    text.append(f"  {_format_tokens(cumulative_tokens)}", style="italic dim")
    return text


def _content_label(content_tokens: int) -> Text:
    text = Text("content", style="dim")
    text.append(f"  {_format_tokens(content_tokens)}", style="italic dim")
    return text


def _add_context_message_details(
    node: Any, message: Any, content: str, message_tokens: int,
) -> None:
    content_node = node.add(_content_label(message_tokens), expand=True)
    for line in content.splitlines() or [content]:
        content_node.add_leaf(Text(line if line else " ", style="#c9d1d9"))
    if getattr(message, "name", None):
        node.add_leaf(Text(f"name: {getattr(message, 'name')}", style="dim"))
    if getattr(message, "tool_call_id", None):
        node.add_leaf(
            Text(f"tool_call_id: {getattr(message, 'tool_call_id')}", style="dim")
        )
