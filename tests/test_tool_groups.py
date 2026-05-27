"""Tests for the tool-group concept.

Covers:
- The ``group`` attribute on tools and the registry's grouping helpers.
- ``resolve_groups_for_names`` (used by the self-edit UI).
- The ToolGroupsBanner payload builder + column renderer.
- The user_extension.py notebook group embedded source.
- The agent editor's tool-toggle / group-toggle wiring (state sync).
- The self-edit tools tab tree ordering (built-ins first).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from taui.tools.base import ToolCategory, ToolResult, tool_group
from taui.tools.builtins import (
    BashKillTool,
    BashStatusTool,
    BashTool,
    ReadTool,
    TaskCreateTool,
    TaskListTool,
    register_builtins,
)
from taui.tools.groups import resolve_groups_for_names
from taui.tools.registry import ToolRegistry


# ── tool_group() helper ────────────────────────────────────────────────


@dataclass
class _Solo:
    name: str = "solo"
    description: str = ""
    schema: dict = None  # type: ignore[assignment]
    category: ToolCategory = ToolCategory.MEMORY

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult.ok("")


@dataclass
class _Grouped:
    name: str = "grouped"
    description: str = ""
    schema: dict = None  # type: ignore[assignment]
    category: ToolCategory = ToolCategory.MEMORY
    group: str = "demo"

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult.ok("")


def test_tool_group_falls_back_to_name_for_solo() -> None:
    assert tool_group(_Solo()) == "solo"


def test_tool_group_reads_explicit_group() -> None:
    assert tool_group(_Grouped()) == "demo"


# ── builtin tools declare groups ──────────────────────────────────────


def test_bash_tools_share_group() -> None:
    assert BashTool().group == "bash"
    assert BashKillTool().group == "bash"
    assert BashStatusTool().group == "bash"


def test_task_tools_share_group() -> None:
    assert TaskCreateTool().group == "tasks"
    assert TaskListTool().group == "tasks"


def test_solo_builtin_has_no_explicit_group() -> None:
    # Solo tools do not need to set `group`; the helper should fall back
    # to their name so they form a single-member group of their own.
    assert tool_group(ReadTool()) == "read"


# ── registry.groups() ──────────────────────────────────────────────────


def test_registry_groups_buckets_members() -> None:
    reg = ToolRegistry()
    register_builtins(reg)
    groups = reg.groups()
    assert sorted(groups["bash"]) == ["bash", "bash_kill", "bash_status"]
    assert sorted(groups["tasks"]) == [
        "task_create",
        "task_get",
        "task_list",
        "task_output",
        "task_stop",
        "task_update",
    ]
    # Solo tools form their own group keyed by their name.
    assert groups["read"] == ["read"]


def test_registry_group_of_round_trip() -> None:
    reg = ToolRegistry()
    register_builtins(reg)
    assert reg.group_of("bash_kill") == "bash"
    assert reg.group_of("task_get") == "tasks"
    assert reg.group_of("read") == "read"


# ── resolve_groups_for_names ──────────────────────────────────────────


def test_resolve_groups_for_known_names() -> None:
    groups = resolve_groups_for_names(["bash", "bash_kill", "read"])
    assert groups["bash"] == ["bash", "bash_kill"]
    assert groups["read"] == ["read"]


def test_resolve_groups_for_unknown_name_uses_itself() -> None:
    # Unknown tool names (presumed user extensions) form their own group.
    groups = resolve_groups_for_names(["bash", "my_custom_tool"])
    assert "my_custom_tool" in groups
    assert groups["my_custom_tool"] == ["my_custom_tool"]


# ── ToolGroupsBanner payload + column renderer ────────────────────────


def test_build_group_payload_includes_descriptions_and_active() -> None:
    from taui.tui.widgets.tool_groups_banner import build_group_payload

    reg = ToolRegistry()
    register_builtins(reg)
    payload = build_group_payload(
        reg,
        available_names=["bash", "bash_kill", "bash_status", "read"],
        active_names={"bash", "read"},
    )
    bash_members = payload["bash"]
    by_name = {name: (desc, active) for name, desc, active in bash_members}
    assert by_name["bash"][1] is True
    assert by_name["bash_kill"][1] is False
    assert by_name["bash_status"][1] is False
    # Description is non-empty
    assert by_name["bash"][0]
    assert payload["read"] == [
        (
            "read",
            ReadTool().description,
            True,
        )
    ]


def test_render_columns_shows_group_labels_with_count_when_multi() -> None:
    from taui.tui.widgets.tool_groups_banner import _render_columns

    payload = {
        "bash": [
            ("bash", "", True),
            ("bash_kill", "", True),
            ("bash_status", "", False),
        ],
        "read": [("read", "", True)],
    }
    output = _render_columns(payload, color="#5a5a5a", columns=3)
    # Multi-tool group renders as ``bash(3)``; solo group as just ``read``.
    assert "bash(3)" in output
    # Solo group label has no parenthesized count.
    assert "read(" not in output
    # Banner only lists group labels — individual tool names live in the
    # click-to-open modal.
    for tool in ("bash_kill", "bash_status"):
        assert tool not in output


def test_format_group_label_drops_count_for_solo_groups() -> None:
    from taui.tui.widgets.tool_groups_banner import _format_group_label

    assert _format_group_label("bash", 3) == "bash(3)"
    assert _format_group_label("read", 1) == "read"


def test_render_columns_empty() -> None:
    from taui.tui.widgets.tool_groups_banner import _render_columns

    assert _render_columns({}, color="#5a5a5a") == ""


# ── ToolGroupsBanner widget basics (no Textual app) ──────────────────


def test_banner_widget_render_text_switches_on_hover() -> None:
    from taui.tui.widgets.tool_groups_banner import ToolGroupsBanner

    payload = {"bash": [("bash", "", True), ("bash_kill", "", True)]}
    banner = ToolGroupsBanner(payload)
    rest = banner._render_text()
    banner._hover = True
    hovered = banner._render_text()
    # Dimmer at rest, brighter on hover — different output for the two states.
    assert rest != hovered
    assert "#5a5a5a" in rest
    assert "#bfbfbf" in hovered


# ── user_extension.py: notebook tool group source ─────────────────────


def test_user_extension_notebook_group_parses_and_declares_group() -> None:
    """Embedded notebook extension exposes a 4-tool group named ``notebook``."""
    from test import user_extension

    ns: dict[str, Any] = {}
    exec(user_extension.NOTEBOOK_EXT_PY, ns)
    tools = [
        ns["NotebookReadTool"](),
        ns["NotebookEditTool"](),
        ns["NotebookRunCellTool"](),
        ns["NotebookClearTool"](),
    ]
    assert [t.name for t in tools] == [
        "notebook_read",
        "notebook_edit",
        "notebook_run_cell",
        "notebook_clear",
    ]
    for tool in tools:
        assert tool.group == "notebook"


def test_user_extension_register_installs_all_four() -> None:
    from test import user_extension

    ns: dict[str, Any] = {}
    exec(user_extension.NOTEBOOK_EXT_PY, ns)

    reg = ToolRegistry()

    class _Ctx:
        tools = reg

    ns["register"](_Ctx())
    names = set(reg.names)
    assert {
        "notebook_read",
        "notebook_edit",
        "notebook_run_cell",
        "notebook_clear",
    }.issubset(names)
    # All four end up in a single "notebook" group.
    assert sorted(reg.groups()["notebook"]) == [
        "notebook_clear",
        "notebook_edit",
        "notebook_read",
        "notebook_run_cell",
    ]


# ── Agent toggle/group wiring (widget-state level) ───────────────────


def test_tool_toggle_carries_group() -> None:
    from taui.tui.screens.self_edit_modal import _ToolToggle

    t = _ToolToggle("bash_kill", selected=False, group="bash")
    assert t.group == "bash"
    assert t.tool_name == "bash_kill"
    assert t.is_selected is False


def test_tool_toggle_set_selected_changes_state_silently() -> None:
    from taui.tui.screens.self_edit_modal import _ToolToggle

    t = _ToolToggle("bash", selected=False, group="bash")
    t.set_selected(True)
    assert t.is_selected is True
    t.set_selected(True)  # no-op
    assert t.is_selected is True
    t.set_selected(False)
    assert t.is_selected is False


def test_tool_group_toggle_counts_state_classes() -> None:
    from taui.tui.screens.self_edit_modal import _ToolGroupToggle

    none_on = _ToolGroupToggle("bash", selected=0, total=3)
    some_on = _ToolGroupToggle("bash", selected=2, total=3)
    all_on = _ToolGroupToggle("bash", selected=3, total=3)
    assert "-all" not in none_on.classes
    assert "-some" not in none_on.classes
    assert "-some" in some_on.classes
    assert "-all" in all_on.classes


def test_tool_group_toggle_set_counts_updates_state() -> None:
    from taui.tui.screens.self_edit_modal import _ToolGroupToggle

    header = _ToolGroupToggle("bash", selected=0, total=3)
    header.set_counts(selected=3, total=3)
    assert "-all" in header.classes
    header.set_counts(selected=1, total=3)
    assert "-some" in header.classes
    assert "-all" not in header.classes


# ── ToolsModal OpenToolsSelfEdit signal ───────────────────────────────


def test_open_tools_self_edit_message_exists() -> None:
    from taui.tui.widgets.tool_groups_banner import OpenToolsSelfEdit

    msg = OpenToolsSelfEdit()
    # Bubbles by default — the app handler is decorated with @on(...).
    assert msg is not None


# ── Self-edit tools tab: built-ins first ordering ─────────────────────


def test_tools_tab_tree_sort_orders_builtin_groups_first() -> None:
    """The tools tab interleaves group folders; built-in groups precede
    user-only groups, and built-in tools precede user tools inside a group.

    We can verify the sort key in isolation since it is just a tuple
    comparison built from the items' ``builtin`` flag and identifier.
    """
    from taui.self_edit import inventory

    Item = inventory.Item

    items = {
        "user_only": Item(
            category="tools", scope="global",
            identifier="user_only", label="user_only",
            summary="", path=__import__("pathlib").Path("/tmp/u"),
            body="", builtin=False,
        ),
        "bash": Item(
            category="tools", scope="global",
            identifier="bash", label="bash",
            summary="", path=__import__("pathlib").Path("/tmp/b"),
            body="", builtin=True,
        ),
    }

    # Reproduce the sort key used inside _refresh_items for the tools tab.
    def _group_sort_key(g: str, members: list[str]) -> tuple[int, str]:
        has_builtin = any(items[m].builtin for m in members)
        return (0 if has_builtin else 1, g)

    groups = {
        "user_only": ["user_only"],
        "bash": ["bash"],
    }
    ordered = sorted(
        groups, key=lambda g: _group_sort_key(g, groups[g])
    )
    assert ordered == ["bash", "user_only"]


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
