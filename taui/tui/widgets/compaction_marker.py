"""Horizontal-rule marker mounted in the chat scroll when compaction runs.

Renders a full-width dimmed rule with a centered label, e.g.

    ─────── context compacted · 47 msgs · 142.3k → 38.1k ───────

The rule re-stretches on resize so it always spans the chat scroll width.
"""

from __future__ import annotations

from textual import events
from textual.widgets import Static


def _short_tokens(n: int) -> str:
    """Format a token count compactly: 142_300 → '142.3k', 0 → '0'."""
    if n < 1_000:
        return str(n)
    return f"{n / 1_000:.1f}k"


class CompactionMarker(Static):
    """A horizontal-rule widget showing a compaction event."""

    DEFAULT_CSS = """
    CompactionMarker {
        height: 1;
        margin: 1 0 1 0;
        color: #6e7681;
        background: transparent;
    }
    """

    def __init__(
        self,
        removed: int,
        before_tokens: int,
        after_tokens: int,
        *,
        kind: str = "auto",
    ) -> None:
        super().__init__("", markup=True)
        self._removed = removed
        self._before_tokens = before_tokens
        self._after_tokens = after_tokens
        self._kind = kind

    def _label(self) -> str:
        if self._removed == 0:
            return "context compacted"
        return (
            f"context compacted · {self._removed} msgs · "
            f"{_short_tokens(self._before_tokens)} → "
            f"{_short_tokens(self._after_tokens)}"
        )

    def _render_line(self, width: int) -> str:
        label = self._label()
        # Reserve one space of padding on each side of the label.
        padded = f" {label} "
        rule_chars = max(0, width - len(padded))
        left = rule_chars // 2
        right = rule_chars - left
        return f"[dim]{'─' * left}[/dim]{padded}[dim]{'─' * right}[/dim]"

    def on_mount(self, _event: events.Mount) -> None:
        self.update(self._render_line(self.size.width or 80))

    def on_resize(self, event: events.Resize) -> None:
        self.update(self._render_line(event.size.width or 80))
