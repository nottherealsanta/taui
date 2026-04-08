"""Pre/Post tool-use hooks — inspired by claw-code's hook pipeline.

Hooks let users run shell snippets **or** Python callables before/after
every tool execution.  A *PreToolUse* hook can deny a tool call (non-zero
exit or returning a ``HookRunResult`` with ``denied=True``).  A
*PostToolUse* hook can annotate or override the tool result.

Shell hooks are configured in ``Settings.hooks``
(see ``taui/config/settings.py``).

Programmatic hooks implement the ``PreToolHook`` or ``PostToolHook``
protocol and are registered via ``HookRunner.register_pre()`` /
``HookRunner.register_post()``.  This is how internal features (cost
tracking, bash safety, spec guards) participate in the hook pipeline
without requiring external shell scripts.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ── Hook result ───────────────────────────────────────────────────────────────


@dataclass(slots=True)
class HookRunResult:
    """Outcome of running a hook batch (pre or post)."""

    denied: bool = False
    messages: list[str] = field(default_factory=list)

    def is_denied(self) -> bool:
        return self.denied


# ── Programmatic hook protocols (claw-code pattern) ───────────────────────────


@dataclass(slots=True)
class PreHookContext:
    """Context passed to pre-tool-use hooks."""

    tool_name: str
    arguments: dict[str, Any]
    agent_id: str | None = None
    session_id: str | None = None


@dataclass(slots=True)
class PostHookContext:
    """Context passed to post-tool-use hooks."""

    tool_name: str
    arguments: dict[str, Any]
    output: str
    is_error: bool
    duration_ms: int = 0
    agent_id: str | None = None
    session_id: str | None = None


@runtime_checkable
class PreToolHook(Protocol):
    """A programmatic pre-tool-use hook.

    Return a ``HookRunResult``.  Set ``denied=True`` to block the call.
    """

    name: str

    def __call__(self, ctx: PreHookContext) -> HookRunResult: ...


@runtime_checkable
class PostToolHook(Protocol):
    """A programmatic post-tool-use hook.

    Return a ``HookRunResult``.  If ``denied=True`` the tool result is
    marked as an error.
    """

    name: str

    def __call__(self, ctx: PostHookContext) -> HookRunResult: ...


# ── Shell hook config ─────────────────────────────────────────────────────────


@dataclass(slots=True)
class HookConfig:
    """Shell snippets executed before/after every tool use."""

    pre_tool_use: list[str] = field(default_factory=list)
    post_tool_use: list[str] = field(default_factory=list)


# ── Hook runner ───────────────────────────────────────────────────────────────


class HookRunner:
    """Executes pre/post tool-use hooks (shell + programmatic).

    **Shell hooks** receive environment variables describing the tool call:
      - ``TAUI_TOOL_NAME`` — name of the tool being called
      - ``TAUI_TOOL_INPUT`` — JSON string of tool arguments
      - ``TAUI_TOOL_OUTPUT`` (post only) — tool output text
      - ``TAUI_TOOL_IS_ERROR`` (post only) — "true" or "false"

    **Programmatic hooks** receive a typed context dataclass and return
    ``HookRunResult`` directly.

    A pre-tool hook that denies **stops** the pipeline — the tool call
    is not executed.
    """

    def __init__(self, config: HookConfig | None = None) -> None:
        self._config = config or HookConfig()
        self._pre_hooks: list[PreToolHook] = []
        self._post_hooks: list[PostToolHook] = []

    @classmethod
    def from_hook_config(cls, config: HookConfig) -> "HookRunner":
        return cls(config)

    # ── Registration ──────────────────────────────────────────────────

    def register_pre(self, hook: PreToolHook) -> None:
        """Register a programmatic pre-tool-use hook."""
        self._pre_hooks.append(hook)

    def register_post(self, hook: PostToolHook) -> None:
        """Register a programmatic post-tool-use hook."""
        self._post_hooks.append(hook)

    def has_hooks(self) -> bool:
        return bool(
            self._config.pre_tool_use
            or self._config.post_tool_use
            or self._pre_hooks
            or self._post_hooks
        )

    # ── Pre-tool hooks ────────────────────────────────────────────────

    def run_pre_tool_use(
        self,
        tool_name: str,
        tool_input: str,
        *,
        agent_id: str | None = None,
        session_id: str | None = None,
        arguments: dict[str, Any] | None = None,
    ) -> HookRunResult:
        """Run all PreToolUse hooks.  Returns denied=True if any hook fails.

        Programmatic hooks run first, then shell hooks.  First denial
        stops the chain.
        """
        result = HookRunResult()

        # 1. Programmatic hooks
        if arguments is None:
            import json as _json

            try:
                arguments = _json.loads(tool_input)
            except (ValueError, TypeError):
                arguments = {}

        pre_ctx = PreHookContext(
            tool_name=tool_name,
            arguments=arguments,
            agent_id=agent_id,
            session_id=session_id,
        )

        for hook in self._pre_hooks:
            try:
                hook_result = hook(pre_ctx)
            except Exception as exc:
                logger.warning(
                    "Programmatic PreToolUse hook %s raised: %s",
                    getattr(hook, "name", "?"),
                    exc,
                )
                hook_result = HookRunResult(
                    denied=False,
                    messages=[f"Hook '{getattr(hook, 'name', '?')}' error: {exc}"],
                )

            result.messages.extend(hook_result.messages)
            if hook_result.denied:
                result.denied = True
                return result

        # 2. Shell hooks
        env_extra = {
            "TAUI_TOOL_NAME": tool_name,
            "TAUI_TOOL_INPUT": tool_input,
        }
        for script in self._config.pre_tool_use:
            outcome = _run_shell_hook(script, env_extra)
            if outcome.stdout:
                result.messages.append(outcome.stdout)
            if outcome.exit_code != 0:
                result.denied = True
                if not outcome.stdout:
                    result.messages.append(f"PreToolUse hook denied tool `{tool_name}`")
                break  # first denial stops the chain
        return result

    # ── Post-tool hooks ───────────────────────────────────────────────

    def run_post_tool_use(
        self,
        tool_name: str,
        tool_input: str,
        tool_output: str,
        is_error: bool,
        *,
        duration_ms: int = 0,
        agent_id: str | None = None,
        session_id: str | None = None,
        arguments: dict[str, Any] | None = None,
    ) -> HookRunResult:
        """Run all PostToolUse hooks.  A failure marks the result as error."""
        result = HookRunResult()

        # 1. Programmatic hooks
        if arguments is None:
            import json as _json

            try:
                arguments = _json.loads(tool_input)
            except (ValueError, TypeError):
                arguments = {}

        post_ctx = PostHookContext(
            tool_name=tool_name,
            arguments=arguments,
            output=tool_output,
            is_error=is_error,
            duration_ms=duration_ms,
            agent_id=agent_id,
            session_id=session_id,
        )

        for hook in self._post_hooks:
            try:
                hook_result = hook(post_ctx)
            except Exception as exc:
                logger.warning(
                    "Programmatic PostToolUse hook %s raised: %s",
                    getattr(hook, "name", "?"),
                    exc,
                )
                hook_result = HookRunResult(
                    denied=False,
                    messages=[f"Hook '{getattr(hook, 'name', '?')}' error: {exc}"],
                )

            result.messages.extend(hook_result.messages)
            if hook_result.denied:
                result.denied = True

        # 2. Shell hooks
        env_extra = {
            "TAUI_TOOL_NAME": tool_name,
            "TAUI_TOOL_INPUT": tool_input,
            "TAUI_TOOL_OUTPUT": tool_output,
            "TAUI_TOOL_IS_ERROR": "true" if is_error else "false",
        }
        for script in self._config.post_tool_use:
            outcome = _run_shell_hook(script, env_extra)
            if outcome.stdout:
                result.messages.append(outcome.stdout)
            if outcome.exit_code != 0:
                result.denied = True
        return result


# ── Built-in programmatic hooks ──────────────────────────────────────────────


class BashSafetyHook:
    """Pre-tool hook that blocks dangerous bash commands.

    Denies commands that match known destructive patterns (rm -rf /,
    fork bombs, etc.) unless they target safe paths.
    """

    name = "bash_safety"

    _DANGEROUS_PATTERNS = (
        "rm -rf /",
        "rm -rf /*",
        "mkfs.",
        "dd if=",
        ":(){",  # fork bomb
        "chmod -R 777 /",
        "> /dev/sd",
        "mv / ",
    )

    def __call__(self, ctx: PreHookContext) -> HookRunResult:
        if ctx.tool_name != "bash":
            return HookRunResult()

        command = ctx.arguments.get("command", "")
        if not isinstance(command, str):
            return HookRunResult()

        for pattern in self._DANGEROUS_PATTERNS:
            if pattern in command:
                return HookRunResult(
                    denied=True,
                    messages=[
                        f"BashSafetyHook: blocked dangerous command "
                        f"matching pattern '{pattern}'"
                    ],
                )
        return HookRunResult()


# ── Shell hook execution ─────────────────────────────────────────────────────


@dataclass(slots=True)
class _ShellHookOutcome:
    exit_code: int
    stdout: str


def _run_shell_hook(
    script: str,
    env_extra: dict[str, str],
    timeout_sec: int = 10,
) -> _ShellHookOutcome:
    """Run a shell snippet with extra env vars. Returns exit code + stdout."""
    import os

    env = {**os.environ, **env_extra}
    try:
        proc = subprocess.run(
            ["sh", "-lc", script],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            env=env,
        )
        return _ShellHookOutcome(
            exit_code=proc.returncode,
            stdout=proc.stdout.strip(),
        )
    except subprocess.TimeoutExpired:
        logger.warning("Hook timed out after %ss: %s", timeout_sec, script[:80])
        return _ShellHookOutcome(exit_code=1, stdout="Hook timed out")
    except Exception as exc:
        logger.warning("Hook execution failed: %s — %s", script[:80], exc)
        return _ShellHookOutcome(exit_code=1, stdout=f"Hook error: {exc}")


def merge_hook_feedback(messages: list[str], output: str, denied: bool) -> str:
    """Merge hook feedback messages into tool output text."""
    if not messages:
        return output
    sections: list[str] = []
    if output.strip():
        sections.append(output)
    label = "Hook feedback (denied)" if denied else "Hook feedback"
    sections.append(f"{label}:\n" + "\n".join(messages))
    return "\n\n".join(sections)
