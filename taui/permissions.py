"""Permission ruleset DSL — pattern-based tool access control.

Rules map (tool_name, argument_pattern) → PolicyDecision.
Patterns use fnmatch glob syntax. Evaluation order: longest pattern first.
Layers: agent → project → global (first match wins per layer, then cascade).

Config format (TOML):
    [taui.permission]
    read = { "*" = "allow", "*.env" = "ask", ".env.example" = "allow" }
    bash = { "git status" = "allow", "git push" = "ask", "*" = "ask" }
    edit = { "src/**" = "allow", "*" = "ask" }
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from typing import Any

from taui.tools.executor import PolicyDecision


@dataclass(slots=True)
class PermissionRule:
    """A single permission rule."""

    tool: str
    pattern: str
    action: PolicyDecision

    @property
    def specificity(self) -> int:
        """Longer patterns are more specific (no wildcards = most specific)."""
        # Count non-wildcard characters for specificity
        return len(self.pattern.replace("*", "").replace("?", ""))


class PermissionRuleset:
    """Layered pattern-based permission rules.

    Rules are evaluated in order: most specific pattern first (longest prefix).
    Layers cascade: agent → project → global.
    """

    def __init__(self) -> None:
        self._agent_rules: list[PermissionRule] = []
        self._project_rules: list[PermissionRule] = []
        self._global_rules: list[PermissionRule] = []

    def add_rules(
        self,
        rules: dict[str, dict[str, str]],
        layer: str = "project",
    ) -> None:
        """Add rules from a config dict.

        Args:
            rules: {tool_name: {pattern: action_str, ...}, ...}
            layer: "agent", "project", or "global"
        """
        parsed: list[PermissionRule] = []
        for tool, patterns in rules.items():
            for pattern, action_str in patterns.items():
                normalized = action_str.lower()
                # "allow" maps to AUTO, "ask" maps to CONFIRM
                if normalized == "allow":
                    normalized = "auto"
                elif normalized == "ask":
                    normalized = "confirm"
                try:
                    action = PolicyDecision(normalized)
                except ValueError:
                    continue
                parsed.append(PermissionRule(tool=tool, pattern=pattern, action=action))

        # Sort by specificity descending (most specific first)
        parsed.sort(key=lambda r: r.specificity, reverse=True)

        if layer == "agent":
            self._agent_rules = parsed
        elif layer == "project":
            self._project_rules = parsed
        else:
            self._global_rules = parsed

    def decide(self, tool_name: str, subject: str = "") -> PolicyDecision | None:
        """Evaluate rules for a tool call. Returns None if no rule matches.

        Checks agent layer first, then project, then global.
        Within each layer, checks most specific patterns first.
        """
        for layer in (self._agent_rules, self._project_rules, self._global_rules):
            for rule in layer:
                if rule.tool != tool_name:
                    continue
                if fnmatch.fnmatch(subject, rule.pattern):
                    return rule.action
        return None

    def extract_subject(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Extract the subject string for pattern matching from tool arguments."""
        if tool_name == "bash":
            return arguments.get("command", "")
        if tool_name in ("write", "edit", "read"):
            return (
                arguments.get("file_path", "")
                or arguments.get("filePath", "")
                or arguments.get("path", "")
            )
        if tool_name == "glob":
            return arguments.get("pattern", "")
        if tool_name == "grep":
            return arguments.get("pattern", "")
        if tool_name == "git":
            operation = arguments.get("operation", "")
            if not isinstance(operation, str):
                return ""
            args = arguments.get("args", {})
            if not isinstance(args, dict) or not args:
                return operation
            parts = [operation]
            for key in sorted(args):
                value = args[key]
                if isinstance(value, str | int | bool):
                    parts.append(f"{key}={value}")
            return " ".join(parts)
        return ""

    @property
    def all_rules(self) -> list[PermissionRule]:
        """All rules across all layers for inspection."""
        return self._agent_rules + self._project_rules + self._global_rules

    def clear_layer(self, layer: str) -> None:
        if layer == "agent":
            self._agent_rules = []
        elif layer == "project":
            self._project_rules = []
        else:
            self._global_rules = []
