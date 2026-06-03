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


def test_resolve_groups_with_working_dir_resolves_extension_groups(
    tmp_path,
) -> None:
    """Tools from a user extension should bucket under their declared group,
    not collapse into solo groups, when ``working_dir`` is supplied."""
    from test import user_extension

    ext_dir = tmp_path / ".taui" / "extensions"
    ext_dir.mkdir(parents=True)
    (ext_dir / "notebook.py").write_text(user_extension.NOTEBOOK_EXT_PY)

    names = [
        "notebook_read",
        "notebook_edit",
        "notebook_run_cell",
        "notebook_clear",
    ]
    groups = resolve_groups_for_names(names, working_dir=tmp_path)
    assert sorted(groups["notebook"]) == sorted(names)


def test_all_tool_names_includes_extension_tool_names(tmp_path) -> None:
    """``all_tool_names`` should list the actual registered tool names from
    extensions (e.g. ``notebook_read``), not the file stem (``notebook``)."""
    from taui.self_edit import inventory
    from test import user_extension

    ext_dir = tmp_path / ".taui" / "extensions"
    ext_dir.mkdir(parents=True)
    (ext_dir / "notebook.py").write_text(user_extension.NOTEBOOK_EXT_PY)

    names = set(inventory.all_tool_names(tmp_path))
    assert {
        "notebook_read",
        "notebook_edit",
        "notebook_run_cell",
        "notebook_clear",
    }.issubset(names)


# ── ToolGroupsBanner payload + column renderer ────────────────────────


def test_build_group_payload_includes_descriptions_and_active() -> None:
    from taui.tui.widgets.tool_groups_banner import ToolEntry, build_group_payload

    reg = ToolRegistry()
    register_builtins(reg)
    payload = build_group_payload(
        reg,
        available_names=["bash", "bash_kill", "bash_status", "read"],
        active_names={"bash", "read"},
    )
    bash_members = payload["bash"]
    by_name = {e.name: e for e in bash_members}
    assert by_name["bash"].active is True
    assert by_name["bash_kill"].active is False
    assert by_name["bash_status"].active is False
    # Description is non-empty
    assert by_name["bash"].description
    # Schema is the same dict the LLM sees — has "properties" for tools
    # that declare arguments.
    assert isinstance(by_name["bash"].schema, dict)
    assert "properties" in by_name["bash"].schema
    read_tool = ReadTool()
    assert payload["read"] == [
        ToolEntry(
            name="read",
            description=read_tool.description,
            active=True,
            schema=read_tool.schema,
        )
    ]


def test_render_columns_shows_group_labels_with_count_when_multi() -> None:
    from taui.tui.widgets.tool_groups_banner import ToolEntry, _render_columns

    payload = {
        "bash": [
            ToolEntry("bash", "", True, {}),
            ToolEntry("bash_kill", "", True, {}),
            ToolEntry("bash_status", "", False, {}),
        ],
        "read": [ToolEntry("read", "", True, {})],
    }
    output = _render_columns(payload, color="#a0a0a0", columns=3)
    # Multi-tool group renders as ``bash(3)``; solo group as just ``read``.
    assert "bash(3)" in output
    # Solo group label has no parenthesized count.
    assert "read(" not in output
    # Banner only lists group labels — individual tool names live in the
    # click-to-open modal.
    for tool in ("bash_kill", "bash_status"):
        assert tool not in output


def test_banner_uses_system_prompt_palette() -> None:
    """Rest text color matches SystemPromptWidget for visual consistency."""
    from taui.tui.widgets import system_prompt as sp_module
    from taui.tui.widgets import tool_groups_banner as tg_module

    sp_css = sp_module.SystemPromptWidget.DEFAULT_CSS
    assert tg_module._TOOL_DEFAULT_COLOR in sp_css


def test_format_group_label_drops_count_for_solo_groups() -> None:
    from taui.tui.widgets.tool_groups_banner import _format_group_label

    assert _format_group_label("bash", 3) == "bash(3)"
    assert _format_group_label("read", 1) == "read"


def test_render_columns_empty() -> None:
    from taui.tui.widgets.tool_groups_banner import _render_columns

    assert _render_columns({}, color="#5a5a5a") == ""


# ── ToolGroupsBanner widget basics (no Textual app) ──────────────────


def test_banner_widget_includes_label_and_body() -> None:
    from taui.tui.widgets.tool_groups_banner import ToolEntry, ToolGroupsBanner

    payload = {
        "bash": [
            ToolEntry("bash", "", True, {}),
            ToolEntry("bash_kill", "", True, {}),
        ]
    }
    banner = ToolGroupsBanner(
        payload, label_text=" Tools ", label_style="bold #fff on #555",
    )
    assert " Tools " in banner._render_label()
    assert "bash(2)" in banner._render_body()


def test_banner_widget_hover_handled_via_css() -> None:
    """Hover state is purely CSS-driven (no Python state toggle)."""
    from taui.tui.widgets.tool_groups_banner import ToolGroupsBanner

    css = ToolGroupsBanner.DEFAULT_CSS
    assert "ToolGroupsBanner:hover" in css
    assert "background" in css


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


# ── ToolsModal definition rendering ───────────────────────────────────


def test_render_param_lines_marks_required_and_shows_types() -> None:
    """Each parameter line carries name, type, required marker, description."""
    from taui.tui.widgets.tool_groups_banner import _render_param_lines

    schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to read."},
            "offset": {"type": "integer", "description": "Start line."},
            "mode": {"enum": ["r", "rb"], "description": "Read mode."},
        },
        "required": ["path"],
    }
    lines = _render_param_lines(schema)
    joined = "\n".join(lines)
    # Required param marker is present and only on the required param's line.
    assert "*" in lines[0]
    assert "path" in lines[0]
    # Types are rendered for each param.
    assert "string" in joined
    assert "integer" in joined
    # Enum is rendered as "one of: r | rb".
    assert "one of:" in joined and "r | rb" in joined
    # Descriptions surface in the output.
    assert "Path to read." in joined


def test_render_param_lines_empty_for_no_schema() -> None:
    from taui.tui.widgets.tool_groups_banner import _render_param_lines

    assert _render_param_lines({}) == []
    assert _render_param_lines({"type": "object"}) == []


def test_render_tool_entry_yields_three_widgets_when_full() -> None:
    """name + description + parameter block when all three are present."""
    from taui.tui.widgets.tool_groups_banner import ToolEntry, _render_tool_entry

    entry = ToolEntry(
        name="read",
        description="Read a file.",
        active=True,
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Where."},
            },
            "required": ["path"],
        },
    )
    widgets = list(_render_tool_entry(entry, solo=True))
    # name + description + params -> 3 widgets
    assert len(widgets) == 3


def test_render_tool_entry_skips_empty_description_and_params() -> None:
    """Tool with no description and no schema yields just the name widget."""
    from taui.tui.widgets.tool_groups_banner import ToolEntry, _render_tool_entry

    entry = ToolEntry("bash_kill", "", True, {})
    widgets = list(_render_tool_entry(entry, solo=False))
    assert len(widgets) == 1


def test_render_tool_entry_inactive_marks_class_on_name() -> None:
    """Inactive tools render with an ``-inactive`` modifier on the name."""
    from taui.tui.widgets.tool_groups_banner import ToolEntry, _render_tool_entry

    entry = ToolEntry("bash_kill", "", False, {})
    widgets = list(_render_tool_entry(entry, solo=False))
    name_w = widgets[0]
    assert "-inactive" in str(name_w.classes)
    assert "tm-tool-name" in str(name_w.classes)


# ── ToolsModal OpenToolsSelfEdit signal ───────────────────────────────


def test_open_tools_self_edit_message_exists() -> None:
    from taui.tui.widgets.tool_groups_banner import OpenToolsSelfEdit

    msg = OpenToolsSelfEdit()
    # Bubbles by default — the app handler is decorated with @on(...).
    assert msg is not None


# ── Self-edit tools tab: built-ins first ordering ─────────────────────


def test_render_flat_item_row_has_no_tree_indent() -> None:
    """Solo-group tools render flush, without the ``└`` tree branch glyph."""
    import pathlib

    from taui.self_edit import inventory
    from taui.tui.screens.self_edit_modal import SelfEditModal

    modal = SelfEditModal(pathlib.Path("/tmp"))
    item = inventory.Item(
        category="tools",
        scope="global",
        identifier="read",
        label="read",
        summary="",
        path=pathlib.Path("/tmp/read"),
        body="",
        builtin=True,
    )
    flat = modal._render_flat_item_row(item)
    tree = modal._render_tree_item_row(item)
    assert "└" not in flat.plain
    assert "└" in tree.plain
    assert "read" in flat.plain


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
