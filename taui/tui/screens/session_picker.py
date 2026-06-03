"""Session picker modal screen with fuzzy search, content search, and preview."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from datetime import datetime

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, OptionList, Static
from textual.widgets.option_list import Option

SessionContentLoader = Callable[[str], Awaitable[str]]


class SessionPickerScreen(ModalScreen[str | None]):
    """Modal for selecting a previous session to resume."""

    DEFAULT_CSS = """
    SessionPickerScreen {
        align: center middle;
        background: $taui-scrim;
    }
    #session-picker-dialog {
        width: 120;
        max-width: 95%;
        height: auto;
        max-height: 86%;
        background: $taui-dialog-bg;
        border: none;
        padding: 0;
    }
    #session-picker-dialog .dialog-title {
        height: 1;
        width: 100%;
        content-align: center middle;
        color: $primary;
        text-style: bold;
    }
    #session-search-row {
        height: 3;
    }
    #session-search {
        width: 1fr;
        background: $taui-field-bg;
        border: solid $taui-border;
    }
    #session-search:focus {
        border: solid $taui-border-focus;
    }
    #session-content-toggle {
        width: auto;
        min-width: 22;
        height: 3;
        margin: 0 0 0 1;
        content-align: center middle;
        color: $text-muted;
    }
    #session-picker-body {
        height: 20;
    }
    #session-picker-dialog OptionList {
        width: 2fr;
        height: 100%;
        background: $taui-field-bg;
        border: solid $taui-border;
        color: $text;
    }
    #session-picker-dialog OptionList:focus {
        border: solid $taui-border-focus;
    }
    #session-picker-dialog .option-list--option-highlighted {
        background: $taui-option-active;
        color: $foreground;
        text-style: bold;
    }
    #session-preview-pane {
        width: 1fr;
        height: 100%;
        margin: 0 0 0 1;
        padding: 0 1;
        background: $taui-field-bg;
        border: solid $taui-border;
        color: $text;
        scrollbar-size: 1 1;
    }
    #session-preview-pane:focus {
        border: solid $taui-border-focus;
    }
    #session-preview {
        width: 100%;
        color: $text;
    }
    #session-picker-dialog .hint {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    """

    def __init__(
        self,
        sessions: list[dict],
        *,
        current_session_id: str = "",
        load_session_content: SessionContentLoader | None = None,
    ) -> None:
        super().__init__()
        self._sessions = sessions[:50]
        self._sessions_by_id = {
            str(session.get("session_id", "")): session for session in self._sessions
        }
        self._current_session_id = current_session_id
        self._load_session_content = load_session_content
        self._content_search = False
        self._content_loading = False
        self._content_cache: dict[str, str] = {}
        self._ordered = _build_tree_order(self._sessions)

    def compose(self) -> ComposeResult:
        with Container(id="session-picker-dialog"):
            yield Label("[bold]Resume Session[/bold]", classes="dialog-title")
            with Horizontal(id="session-search-row"):
                yield Input(placeholder="Search sessions...", id="session-search")
                yield Button("◇ search content", id="session-content-toggle")
            with Horizontal(id="session-picker-body"):
                yield OptionList(*self._options(), id="session-options")
                with VerticalScroll(id="session-preview-pane"):
                    yield Static(
                        "Press p to preview the highlighted session.",
                        id="session-preview",
                        markup=False,
                    )
            yield Label(
                "Enter resume · p preview · Esc cancel",
                classes="hint",
            )

    def on_mount(self) -> None:
        def focus_search() -> None:
            try:
                self.query_one("#session-search", Input).focus()
            except Exception:
                pass

        self.call_after_refresh(focus_search)

    def _options(self) -> list[Option]:
        return [
            Option(
                _session_prompt(
                    row["session"],
                    row["depth"],
                    current_session_id=self._current_session_id,
                ),
                id=str(row["session"]["session_id"]),
            )
            for row in self._ordered
        ]

    def _filter(self, query: str) -> list[dict]:
        q = query.lower().strip()
        if not q:
            return list(self._sessions)

        substring: list[dict] = []
        subseq: list[dict] = []
        for session in self._sessions:
            target = _session_search_text(session)
            if self._content_search:
                sid = str(session.get("session_id", ""))
                target = f"{target} {self._content_cache.get(sid, '').lower()}"
            if q in target:
                substring.append(session)
            elif _subseq_match(q, target):
                subseq.append(session)
        return substring + subseq

    def _refresh_options(self) -> None:
        try:
            search = self.query_one("#session-search", Input)
            opts = self.query_one("#session-options", OptionList)
        except Exception:
            return
        self._ordered = _build_tree_order(self._filter(search.value))
        opts.clear_options()
        for option in self._options():
            opts.add_option(option)
        if opts.option_count:
            opts.highlighted = 0
        self._clear_preview()

    def _show_session_info(self) -> None:
        """Show session metadata in the preview pane (before pressing p)."""
        sid = self._selected_session_id()
        if not sid:
            self._clear_preview()
            return
        session = self._sessions_by_id.get(sid, {})
        try:
            preview = self.query_one("#session-preview", Static)
        except Exception:
            return
        title = str(session.get("description") or _fallback_name(session))
        msgs = int(session.get("message_count", 0) or 0)
        ago = _time_ago(float(session.get("last_active", 0) or 0))
        mode = str(session.get("mode", "normal"))
        mode_tag = f"\nMode: {mode}" if mode != "normal" else ""
        info = f"{title}\n\nID: {sid}\n{msgs} msgs · {ago}{mode_tag}\n\nPress p to preview content"
        preview.update(info)

    def _clear_preview(self) -> None:
        try:
            preview = self.query_one("#session-preview", Static)
        except Exception:
            return
        preview.update("Select a session to see details.")

    def _selected_session_id(self) -> str | None:
        try:
            opts = self.query_one("#session-options", OptionList)
        except Exception:
            return None
        if opts.option_count == 0:
            return None
        index = opts.highlighted if opts.highlighted is not None else 0
        try:
            option = opts.get_option_at_index(index)
        except Exception:
            return None
        return str(option.id) if option.id is not None else None

    def _move_selection(self, delta: int) -> None:
        try:
            opts = self.query_one("#session-options", OptionList)
        except Exception:
            return
        if opts.option_count == 0:
            return
        current = opts.highlighted if opts.highlighted is not None else 0
        new_index = current + delta
        if new_index < 0:
            # Moving up past the first item — focus the search bar
            self.query_one("#session-search", Input).focus()
            return
        opts.highlighted = new_index % opts.option_count
        opts.focus()

    def _update_content_button(self) -> None:
        try:
            button = self.query_one("#session-content-toggle", Button)
        except Exception:
            return
        if self._content_loading:
            button.label = "⟳ search content"
        elif self._content_search:
            button.label = "◆ search content"
        else:
            button.label = "◇ search content"

    async def _load_missing_content(self) -> None:
        if self._load_session_content is None:
            return
        self._content_loading = True
        self._update_content_button()
        try:
            for session in self._sessions:
                sid = str(session.get("session_id", ""))
                if not sid or sid in self._content_cache:
                    continue
                try:
                    self._content_cache[sid] = await self._load_session_content(sid)
                except Exception:
                    self._content_cache[sid] = ""
        finally:
            self._content_loading = False
            self._update_content_button()
            self._refresh_options()

    async def _preview_selected(self) -> None:
        sid = self._selected_session_id()
        if not sid:
            return
        session = self._sessions_by_id.get(sid, {"session_id": sid})
        try:
            preview = self.query_one("#session-preview", Static)
        except Exception:
            return

        cached = self._content_cache.get(sid)
        if cached is None and self._load_session_content is not None:
            preview.update("Loading preview...")
            try:
                cached = await self._load_session_content(sid)
            except Exception as exc:
                cached = f"Preview failed: {exc}"
            self._content_cache[sid] = cached

        preview.update(_preview_text(session, cached or ""))

    @on(Input.Changed, "#session-search")
    def _on_search_changed(self, _: Input.Changed) -> None:
        self._refresh_options()

    @on(Input.Submitted, "#session-search")
    def _on_search_submit(self, _: Input.Submitted) -> None:
        sid = self._selected_session_id()
        if sid:
            self.dismiss(sid)

    @on(Button.Pressed, "#session-content-toggle")
    def _on_content_toggle(self, event: Button.Pressed) -> None:
        event.stop()
        self._content_search = not self._content_search
        self._update_content_button()
        self._refresh_options()
        if self._content_search and self._load_session_content is not None:
            self.run_worker(
                self._load_missing_content(),
                name="session_content_search",
                exclusive=True,
            )

    @on(OptionList.OptionHighlighted)
    def _on_option_highlighted(self, _: OptionList.OptionHighlighted) -> None:
        self._show_session_info()

    @on(OptionList.OptionSelected)
    def on_option_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = event.option_id
        if option_id is None:
            idx = event.option_index
            if idx < len(self._ordered):
                option_id = str(self._ordered[idx]["session"]["session_id"])
        self.dismiss(str(option_id) if option_id else None)

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            event.stop()
            self.dismiss(None)
            return
        if event.key in ("up", "down"):
            event.stop()
            event.prevent_default()
            self._move_selection(-1 if event.key == "up" else 1)
            return
        if event.key == "p":
            try:
                focused = self.app.focused
            except Exception:
                focused = None
            if isinstance(focused, Input):
                return
            event.stop()
            self.run_worker(
                self._preview_selected(),
                name="session_preview",
                exclusive=True,
            )


def _build_tree_order(sessions: list[dict]) -> list[dict]:
    """Order sessions as a tree based on parent_session_id.

    Returns list of {"session": dict, "depth": int} in display order.
    Root sessions (no parent) come first sorted by last_active desc,
    children are nested under their parent.
    """
    by_id: dict[str, dict] = {}
    children: dict[str, list[dict]] = {}

    for s in sessions:
        sid = str(s.get("session_id", ""))
        by_id[sid] = s
        parent = s.get("parent_session_id")
        if parent and str(parent) != sid:
            children.setdefault(str(parent), []).append(s)

    roots = [
        s
        for s in sessions
        if not s.get("parent_session_id") or str(s.get("parent_session_id")) not in by_id
    ]

    result: list[dict] = []

    def _add(session: dict, depth: int) -> None:
        result.append({"session": session, "depth": depth})
        sid = str(session.get("session_id", ""))
        for child in children.get(sid, []):
            _add(child, depth + 1)

    for root in roots:
        _add(root, 0)

    return result


def _session_prompt(
    session: dict,
    depth: int = 0,
    *,
    current_session_id: str = "",
) -> Text:
    sid = str(session.get("session_id", ""))
    desc = str(session.get("description") or _fallback_name(session))[:40]
    mode = str(session.get("mode", "normal"))
    msgs = int(session.get("message_count", 0) or 0)
    ago = _time_ago(float(session.get("last_active", 0) or 0))
    mode_tag = " [ext]" if mode == "extensions" else ""
    current_tag = " current" if current_session_id and sid == current_session_id else ""

    prefix = ""
    if depth > 0:
        prefix = "  " * (depth - 1) + "├─ "

    text = Text()
    if prefix:
        text.append(prefix, style="dim")
    text.append(f"{desc:<40s}  ", style="white bold" if current_tag else "white")
    text.append(f"{msgs:>3} msgs  {ago}{mode_tag}{current_tag}", style="dim")
    return text


def _session_search_text(session: dict) -> str:
    return " ".join(
        str(part)
        for part in (
            session.get("session_id", ""),
            session.get("description", ""),
            session.get("first_message", ""),
            session.get("mode", ""),
            session.get("model", ""),
        )
        if part
    ).lower()


def _preview_text(session: dict, content: str) -> str:
    title = str(session.get("description") or _fallback_name(session))
    sid = str(session.get("session_id", ""))
    msgs = int(session.get("message_count", 0) or 0)
    ago = _time_ago(float(session.get("last_active", 0) or 0))
    body = content.strip() or "(no replayable content)"
    if len(body) > 6000:
        body = body[:6000].rstrip() + "\n\npreview truncated"
    footer = f"\n\n---\n{title}\nID: {sid} · {msgs} msgs · {ago}"
    return f"{body}{footer}"


def _fallback_name(session: dict) -> str:
    """Label for sessions without a description — first user message or created time."""
    first = (session.get("first_message") or "").strip()
    if first:
        return first
    ts = float(session.get("created_at", 0) or 0)
    if ts <= 0:
        return "(unnamed)"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def _time_ago(ts: float) -> str:
    if ts <= 0:
        return "unknown"
    delta = time.time() - ts
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{int(delta / 60)}m ago"
    if delta < 86400:
        return f"{int(delta / 3600)}h ago"
    return f"{int(delta / 86400)}d ago"


def _subseq_match(query: str, target: str) -> bool:
    """Return True if every char in `query` appears in `target` in order."""
    i = 0
    for ch in target:
        if i < len(query) and ch == query[i]:
            i += 1
    return i == len(query)
