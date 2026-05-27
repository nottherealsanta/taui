"""Context-banner widget for loaded skills.

Mirrors the visual treatment of ``ToolGroupsBanner``: a fixed-column grid of
skill names rendered dim grey at rest, brighter on hover. Clicking the banner
opens a modal listing every loaded skill with its scope and a short
description (the first paragraph of its SKILL.md).
"""

from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

_SKILL_DEFAULT_COLOR = "#a0a0a0"
_SKILL_EMPTY_COLOR = "#5a5a5a"
_DEFAULT_LABEL_STYLE = "bold #ffffff on #8a8a8a"


class SkillsModal(ModalScreen[None]):
    """Modal listing every loaded skill with scope + description."""

    DEFAULT_CSS = """
    SkillsModal {
        align: center middle;
    }
    #skills-modal-dialog {
        width: 80%;
        height: 80%;
        background: $surface;
        border: thick $surface-lighten-1;
        padding: 1 2;
    }
    #skills-modal-dialog .dialog-title {
        width: 100%;
        content-align: center middle;
        padding: 0 0 1 0;
        color: #ff9e64;
        text-style: bold;
    }
    #skills-modal-dialog #sm-scroll {
        height: 1fr;
        border-top: solid $surface-lighten-1;
        padding: 1 0 0 0;
        scrollbar-size-vertical: 1;
    }
    #skills-modal-dialog .sm-skill-name {
        color: #d2a8ff;
        text-style: bold;
        padding: 1 0 0 0;
    }
    #skills-modal-dialog .sm-skill-scope {
        color: #6a6a6a;
        padding: 0 0 0 2;
    }
    #skills-modal-dialog .sm-skill-path {
        color: #6a6a6a;
        padding: 0 0 0 2;
    }
    #skills-modal-dialog .sm-skill-desc {
        color: #c9d1d9;
        padding: 0 0 0 2;
    }
    #skills-modal-dialog .button-container {
        width: 100%;
        height: auto;
        align: center middle;
        padding: 1 0 0 0;
    }
    #skills-modal-dialog #sm-add-button {
        margin: 0 1;
    }
    """

    def __init__(
        self, skills: list[tuple[str, str, str, str]]
    ) -> None:
        super().__init__()
        self._skills = skills

    def compose(self) -> ComposeResult:
        with Container(id="skills-modal-dialog"):
            yield Static(
                f"[bold]Skills  ·  {len(self._skills)} available[/bold]",
                classes="dialog-title",
                markup=True,
            )
            with VerticalScroll(id="sm-scroll"):
                if not self._skills:
                    yield Static("(no skills discovered)", markup=False)
                else:
                    for name, scope, path, desc in self._skills:
                        yield Static(name, classes="sm-skill-name", markup=False)
                        yield Static(
                            f"scope: {scope}",
                            classes="sm-skill-scope",
                            markup=False,
                        )
                        if path:
                            yield Static(
                                f"path: {path}",
                                classes="sm-skill-path",
                                markup=False,
                            )
                        if desc:
                            yield Static(
                                desc, classes="sm-skill-desc", markup=False,
                            )
            with Horizontal(classes="button-container"):
                yield Button(
                    "Add skill…",
                    variant="default",
                    id="sm-add-button",
                    disabled=True,
                )
                yield Button("Close", variant="primary", id="close-button")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "sm-add-button":
            # Stub — implemented later.
            return
        self.dismiss(None)

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self.dismiss(None)


def _render_columns(
    names: list[str], *, color: str, columns: int = 3,
) -> str:
    """Render skill names as fixed-width columns."""
    if not names:
        return ""
    col_width = max((len(n) for n in names), default=0) + 2
    rows: list[str] = []
    for i in range(0, len(names), columns):
        chunk = names[i:i + columns]
        cells = []
        for j, label in enumerate(chunk):
            padded = label if j == len(chunk) - 1 else label.ljust(col_width)
            cells.append(f"[{color}]{padded}[/{color}]")
        rows.append("".join(cells))
    return "\n".join(rows)


class SkillsBanner(Container):
    """Context banner: header label + discovered-skill grid, one widget."""

    DEFAULT_CSS = """
    SkillsBanner {
        width: 100%;
        height: auto;
        margin: 0 1 1 1;
        padding: 0 1 0 1;
        color: #a0a0a0;
    }
    SkillsBanner:hover {
        background: #2a2a2a;
        color: #e8e8e8;
    }
    SkillsBanner .banner-label {
        width: 100%;
        height: auto;
        padding: 0;
        margin: 0 1 0 0;
    }
    SkillsBanner .banner-body {
        width: 100%;
        height: auto;
        padding: 0 1 0 2;
        margin: 0 1 1 1;
    }
    """

    def __init__(
        self,
        skills: list[tuple[str, str, str, str]],
        *,
        label_text: str = "Skills",
        label_style: str = _DEFAULT_LABEL_STYLE,
    ) -> None:
        super().__init__()
        self._skills = skills
        self._label_text = label_text
        self._label_style = label_style

    def compose(self) -> ComposeResult:
        yield Static(
            self._render_label(), classes="banner-label", markup=True,
        )
        yield Static(
            self._render_body(), classes="banner-body", markup=True,
        )

    def _render_label(self) -> str:
        return f"[{self._label_style}] {self._label_text} [/]"

    def _render_body(self) -> str:
        if not self._skills:
            return f"[{_SKILL_EMPTY_COLOR} italic](no skills discovered)[/]"
        return _render_columns(
            [s[0] for s in self._skills], color=_SKILL_DEFAULT_COLOR,
        )

    def set_skills(
        self,
        skills: list[tuple[str, str, str, str]],
        *,
        label_style: str | None = None,
    ) -> None:
        self._skills = skills
        if label_style is not None:
            self._label_style = label_style
        try:
            self.query_one(".banner-body", Static).update(self._render_body())
            self.query_one(".banner-label", Static).update(self._render_label())
        except Exception:
            pass

    async def on_click(self, event: events.Click) -> None:
        event.stop()
        await self.app.push_screen(SkillsModal(self._skills))


def build_skills_payload(
    skill_registry,
) -> list[tuple[str, str, str, str]]:
    """Resolve (name, scope, path, description) for every discovered skill.

    Lists every skill the registry has discovered, regardless of whether it
    is currently loaded into the agent's context — actual load events are
    surfaced as ``skills`` tool calls in the chat stream. Description is the
    first non-empty, non-heading line of the SKILL.md.
    """
    if skill_registry is None:
        return []
    out: list[tuple[str, str, str, str]] = []
    for skill in skill_registry.list_all():
        try:
            content = skill.content or skill.load_content()
        except Exception:
            content = ""
        desc = _first_description_line(content)
        path = str(getattr(skill, "path", "") or "")
        out.append((skill.name, skill.scope, path, desc))
    out.sort(key=lambda s: s[0])
    return out


def _first_description_line(content: str) -> str:
    """Return the first non-empty, non-heading line from SKILL.md content."""
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("---"):
            continue
        if len(line) > 120:
            return line[:117] + "…"
        return line
    return ""
