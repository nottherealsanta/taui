"""Question tool — ask the user for clarification."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from taui.tools.base import ToolCategory, ToolResult


def _normalize_options(raw: Any) -> list[dict[str, Any]] | None:
    """Normalize options into a list of {label, description?} dicts.

    Accepts a list of strings or a list of objects. Returns None if the
    input is not a list. Unknown entries are dropped.
    """
    if not isinstance(raw, list):
        return None
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, str):
            label = item.strip()
            if not label:
                continue
            out.append({"label": label, "description": None})
        elif isinstance(item, dict):
            label = item.get("label")
            if not isinstance(label, str) or not label.strip():
                continue
            desc = item.get("description")
            if desc is not None and not isinstance(desc, str):
                desc = str(desc)
            out.append({"label": label.strip(), "description": desc})
    return out or None


def _normalize_recommended(
    raw: Any, options: list[dict[str, Any]] | None
) -> int | None:
    """Resolve recommended -> 1-indexed int. Accepts int, str (label), or
    string that ends in (recommended) in any option label (legacy)."""
    if not options:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        if 1 <= raw <= len(options):
            return raw
        return None
    if isinstance(raw, str):
        needle = raw.strip().lower()
        if not needle:
            return None
        for i, opt in enumerate(options, 1):
            if opt["label"].lower() == needle:
                return i
        return None
    # Legacy: scan labels for trailing "(recommended)" marker.
    for i, opt in enumerate(options, 1):
        lab = opt["label"].lower()
        if lab.endswith("(recommended)"):
            stripped = opt["label"][: -len("(recommended)")].rstrip()
            opt["label"] = stripped
            return i
    return None


@dataclass
class QuestionTool:
    """Ask the user a question and wait for a response.

    The tool blocks until the user responds. Uses a callback (set by the CLI
    or other frontend) to deliver the question and receive the answer.
    """

    name: str = "question"
    description: str = (
        "Ask the user a question when you need clarification or a decision. "
        "Provide 2–4 suggested options, each with a label and an optional "
        "short description (rendered in gray next to the option). "
        "If you have a preferred option, set `recommended` to the 1-based "
        "index of that option — it will be displayed with a `(recommended)` "
        "marker. Only set `recommended` when you actually have a clear "
        "preference; otherwise omit it."
    )
    category: ToolCategory = ToolCategory.QUESTION
    guidelines: str = (
        "Use `question` when you need user input to proceed. "
        "Don't ask unnecessary questions — only when genuinely uncertain. "
        "Provide 2–4 concise options as objects with `label` and an optional "
        "short `description`. Set `recommended` (1-based index) when one "
        "option is clearly preferable; omit it when the options are "
        "genuinely interchangeable."
    )
    schema: dict[str, Any] = field(default=None)  # type: ignore[assignment]

    # Callback: async (question, options, recommended) -> answer_str | None
    _ask: Any = None

    def __post_init__(self):
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question to ask the user.",
                    },
                    "options": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {
                                    "type": "string",
                                    "description": (
                                        "Short option text (1–5 words). "
                                        "Do NOT include '(Recommended)' here "
                                        "— use the top-level `recommended` "
                                        "field instead."
                                    ),
                                },
                                "description": {
                                    "type": "string",
                                    "description": (
                                        "Optional one-line detail rendered "
                                        "in gray to the right of the option. "
                                        "Use it to clarify trade-offs or "
                                        "implications."
                                    ),
                                },
                            },
                            "required": ["label"],
                        },
                        "description": (
                            "2–4 suggested options. The user can always "
                            "type a custom answer instead."
                        ),
                    },
                    "recommended": {
                        "type": "integer",
                        "description": (
                            "Optional 1-based index of the option you "
                            "recommend. Omit when no option is clearly "
                            "preferable."
                        ),
                    },
                },
                "required": ["question"],
            }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        question = arguments.get("question")
        if not isinstance(question, str) or not question.strip():
            return ToolResult.fail("'question' must be a non-empty string.")

        options = _normalize_options(arguments.get("options"))
        recommended = _normalize_recommended(
            arguments.get("recommended"), options
        )

        if self._ask is None:
            return ToolResult.ok(
                "No interactive mechanism available. Proceed with your best judgment.",
                answered=False,
            )

        try:
            answer = await self._ask(question, options, recommended)
        except TypeError:
            # Backwards-compat: older callbacks took (question, options) with
            # options as a list of plain strings.
            legacy_options = (
                [
                    o["label"] + (" (Recommended)" if i == recommended else "")
                    for i, o in enumerate(options or [], 1)
                ]
                if options
                else None
            )
            try:
                answer = await self._ask(question, legacy_options)
            except Exception as exc:
                return ToolResult.fail(f"Failed to get answer: {exc}")
        except Exception as exc:
            return ToolResult.fail(f"Failed to get answer: {exc}")

        if answer is None:
            return ToolResult.ok(
                "Question was dismissed. Proceed with your best judgment.",
                answered=False,
            )

        return ToolResult.ok(f"User answered: {answer}", answered=True, answer=answer)
