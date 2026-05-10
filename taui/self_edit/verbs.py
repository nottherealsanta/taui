"""Local verb parsing for self-edit mode."""

from __future__ import annotations

import shlex
from dataclasses import dataclass

VERBS = (
    "?",
    "agent",
    "confirm",
    "discard",
    "exit",
    "help",
    "mcp",
    "save",
    "skill",
    "tool",
)

SECTIONS = ("agents", "tools", "skills", "mcp")
SCOPES = ("global", "project")
ASSET_ACTIONS = ("new", "view", "edit", "list", "remove")


@dataclass(frozen=True, slots=True)
class VerbCommand:
    """A parsed self-edit command."""

    verb: str
    args: tuple[str, ...]
    raw_args: str


@dataclass(frozen=True, slots=True)
class VerbParseError(Exception):
    """Raised when input cannot be parsed as a self-edit verb."""

    message: str

    def __str__(self) -> str:
        return self.message


def parse_verb(text: str) -> VerbCommand:
    """Parse a local self-edit command.

    The grammar is intentionally small: first token is the verb, the rest are args.
    A leading slash is accepted so existing slash-completion muscle memory still works.
    """

    stripped = text.strip()
    if not stripped:
        raise VerbParseError("Type a self-edit verb.")
    stripped = stripped.removeprefix("/").strip()
    if not stripped:
        raise VerbParseError("Type a self-edit verb.")
    try:
        parts = tuple(shlex.split(stripped))
    except ValueError as exc:
        raise VerbParseError(str(exc)) from exc
    if not parts:
        raise VerbParseError("Type a self-edit verb.")
    verb = parts[0].lower()
    if verb not in VERBS:
        raise VerbParseError(f"Unknown self-edit verb: {parts[0]}")
    raw_args = stripped[len(parts[0]) :].strip()
    return VerbCommand(verb=verb, args=parts[1:], raw_args=raw_args)


def complete_verb(text: str, *, targets: tuple[str, ...] = ()) -> list[tuple[str, str, bool]]:  # noqa: ARG001
    """Return completion rows for the current self-edit input."""

    text = text.removeprefix("/").lstrip()
    if not text or (" " not in text and not text.endswith(" ")):
        prefix = text.casefold()
        return [
            (verb, _verb_description(verb), True)
            for verb in VERBS
            if verb.startswith(prefix)
        ]

    parts = text.split()
    verb = parts[0].lower() if parts else ""
    prefix = "" if text.endswith(" ") else parts[-1].casefold()

    values: tuple[str, ...] = ()
    if verb in ("agent", "tool", "skill", "mcp"):
        values = ASSET_ACTIONS

    return [(value, "", True) for value in values if value.casefold().startswith(prefix)]


def _verb_description(verb: str) -> str:
    descriptions = {
        "?": "Show valid verbs",
        "agent": "Manage agents",
        "confirm": "Confirm pending action",
        "discard": "Drop pending edits",
        "exit": "Leave self-edit",
        "help": "Show valid verbs",
        "mcp": "Manage MCP servers",
        "save": "Persist pending edits",
        "skill": "Manage skills",
        "tool": "Manage tools",
    }
    return descriptions.get(verb, "Self-edit command")
