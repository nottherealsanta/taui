"""Session tab bar — shows open sessions as clickable tabs."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


class SessionTabBar(Widget):
    """Horizontal tab bar showing all open sessions.

    Badges:
    - ``●`` idle
    - ``⟳`` processing (agent running)
    - ``⚠`` needs approval
    """

    DEFAULT_CSS = """
    SessionTabBar {
        dock: top;
        height: 1;
        width: 100%;
        background: $surface-darken-2;
        layout: horizontal;
        overflow-x: auto;
    }
    SessionTabBar .session-tab {
        width: auto;
        height: 1;
        padding: 0 1;
        background: $surface-darken-2;
    }
    SessionTabBar .session-tab.active {
        background: $surface;
        text-style: bold;
    }
    SessionTabBar .session-tab:hover {
        background: $surface-darken-1;
    }
    SessionTabBar .new-tab-btn {
        width: auto;
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    SessionTabBar .new-tab-btn:hover {
        color: $text;
    }
    """

    class TabClicked(Message):
        """User clicked a session tab."""

        def __init__(self, session_id: str) -> None:
            super().__init__()
            self.session_id = session_id

    class TabClosed(Message):
        """User closed a session tab."""

        def __init__(self, session_id: str) -> None:
            super().__init__()
            self.session_id = session_id

    class NewTabClicked(Message):
        """User clicked the + button."""

    tab_count = reactive(0)

    def compose(self) -> ComposeResult:
        yield Static("[dim]+[/dim]", classes="new-tab-btn", markup=True)

    def refresh_tabs(
        self,
        tabs: list[dict],
        active_id: str | None = None,
    ) -> None:
        """Rebuild the tab bar from a list of tab descriptors.

        Each dict has: session_id, label, is_processing, needs_approval.
        """
        # Remove existing tab children (keep the + button)
        existing_tabs = [c for c in self.children if c.has_class("session-tab")]
        for child in existing_tabs:
            child.remove()

        plus_btn = None
        for child in self.children:
            if child.has_class("new-tab-btn"):
                plus_btn = child
                break

        # Build a set of IDs still in the DOM (pending async removal) to avoid
        # DuplicateIds errors when mounting new tabs with the same session ID.
        pending_ids = {c.id for c in self.children if c.id}

        for tab_info in tabs:
            sid = tab_info["session_id"]
            label = tab_info.get("label", sid[:8])
            is_active = sid == active_id
            is_processing = tab_info.get("is_processing", False)
            needs_approval = tab_info.get("needs_approval", False)

            if needs_approval:
                badge = " ⚠"
                badge_color = "#f0c808"
            elif is_processing:
                badge = " ⟳"
                badge_color = "#3fb950"
            else:
                badge = ""
                badge_color = ""

            row = Text()
            if is_active:
                row.append(f"● {label}", style="bold")
            else:
                row.append(f"○ {label}", style="dim")
            if badge:
                row.append(badge, style=badge_color)

            # Use no ID if a widget with that ID is still pending removal
            tab_id = f"tab-{sid}" if f"tab-{sid}" not in pending_ids else None
            tab_widget = Static(
                row,
                classes="session-tab" + (" active" if is_active else ""),
                id=tab_id,
            )
            tab_widget._session_id = sid  # type: ignore[attr-defined]
            if plus_btn is not None:
                self.mount(tab_widget, before=plus_btn)
            else:
                self.mount(tab_widget)

        self.tab_count = len(tabs)

    def on_click(self, event) -> None:
        """Route clicks on tab children to messages."""
        target = event.widget
        if target is self:
            return
        if target.has_class("new-tab-btn"):
            self.post_message(self.NewTabClicked())
            return
        # Walk up to find a session-tab
        widget = target
        while widget is not None and widget is not self:
            if hasattr(widget, "_session_id"):
                self.post_message(self.TabClicked(widget._session_id))
                return
            widget = widget.parent
