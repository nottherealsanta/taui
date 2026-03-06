from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from taui.config.settings import BashPolicySettings, Settings

PolicyDecision = Literal["allow", "confirm", "deny"]


@dataclass(slots=True)
class ToolDecision:
    decision: PolicyDecision
    reason: str


@dataclass(slots=True)
class Policy:
    auto_approve: set[str]
    confirm: set[str]
    deny: set[str]
    bash: BashPolicySettings

    @classmethod
    def from_settings(cls, settings: Settings) -> "Policy":
        return cls(
            auto_approve=set(settings.policy.auto_approve),
            confirm=set(settings.policy.confirm),
            deny=set(settings.policy.deny),
            bash=settings.policy_bash,
        )

    def evaluate(self, tool_name: str) -> ToolDecision:
        if tool_name in self.deny:
            return ToolDecision(
                decision="deny", reason=f"Tool '{tool_name}' is denied by policy."
            )
        if tool_name in self.confirm:
            return ToolDecision(
                decision="confirm", reason=f"Tool '{tool_name}' requires approval."
            )
        if tool_name in self.auto_approve:
            return ToolDecision(
                decision="allow", reason=f"Tool '{tool_name}' is auto-approved."
            )
        return ToolDecision(
            decision="confirm",
            reason=f"Tool '{tool_name}' is not categorized and requires approval.",
        )
