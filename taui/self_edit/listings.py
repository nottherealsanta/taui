"""Plain-text renderers for self-edit mode."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from taui.self_edit.store import AgentProfile, ExtensionSource, ToolSource


def agents_listing(agents: dict[str, AgentProfile], *, scope: str) -> str:
    lines = [f"agents (creation scope: {scope})"]
    for agent_id, profile in sorted(agents.items()):
        model = " / ".join(x for x in (profile.provider, profile.model) if x) or "inherit"
        lines.append(f"  {agent_id:3s}  {profile.name:20s}  {model}")
    return "\n".join(lines)


def agent_detail(profile: AgentProfile) -> str:
    tools = ", ".join(profile.allowed_tools) if profile.allowed_tools else "all"
    model = " / ".join(x for x in (profile.provider, profile.model) if x) or "inherit"
    prompt_path = str(profile.prompt_path) if profile.prompt_path else "(inline)"
    return "\n".join(
        [
            f"agent {profile.id}",
            f"name:        {profile.name}",
            f"model:       {model}",
            f"prompt:      {prompt_path}",
            f"tools:       {tools}",
            "",
            profile.prompt,
        ]
    )


def tools_listing(sources: dict[str, ToolSource], registry: Any) -> str:
    lines = ["tools"]
    for name in registry.names:
        source = sources.get(name)
        tool = registry.get(name)
        path = str(source.path) if source and source.path else "built-in"
        lines.append(f"  {name:24s}  {tool.category.value:12s}  {path}")
    return "\n".join(lines)


def tool_detail(name: str, source: ToolSource | None, registry: Any) -> str:
    tool = registry.get(name)
    path = str(source.path) if source and source.path else "built-in"
    schema = json.dumps(tool.schema, indent=2) if isinstance(tool.schema, dict) else "{}"
    return "\n".join(
        [
            f"tool {name}",
            f"category:    {tool.category.value}",
            f"source:      {path}",
            f"description: {tool.description}",
            "",
            schema,
        ]
    )


def extensions_listing(extensions: dict[str, ExtensionSource]) -> str:
    lines = ["extensions"]
    for name, ext in sorted(extensions.items()):
        status = "error" if ext.error else ("loaded" if ext.loaded else "not loaded")
        path = str(ext.path) if ext.path else "built-in"
        lines.append(f"  {name:24s}  {ext.scope:8s}  {status:10s}  {path}")
    return "\n".join(lines)


def extension_detail(ext: ExtensionSource) -> str:
    status = "error" if ext.error else ("loaded" if ext.loaded else "not loaded")
    lines = [
        f"extension {ext.name}",
        f"scope:       {ext.scope}",
        f"status:      {status}",
        f"path:        {ext.path or 'built-in'}",
    ]
    if ext.description:
        lines.append(f"description: {ext.description}")
    if ext.error:
        lines.extend(["", f"error: {ext.error}"])
    return "\n".join(lines)


def skills_listing(skills: list[Any]) -> str:
    lines = ["skills"]
    if not skills:
        lines.append("  (none discovered)")
    for skill in skills:
        lines.append(f"  {skill.name:24s}  {skill.scope:8s}  {skill.path}")
    return "\n".join(lines)


def config_listing(config: Any) -> str:
    prompt = config.system_prompt.strip()
    if len(prompt) > 700:
        prompt = f"{prompt[:697].rstrip()}..."
    return "\n".join(
        [
            "config",
            f"provider:      {config.provider}",
            f"model:         {config.model}",
            f"max_turns:     {config.max_turns}",
            f"working_dir:   {Path(config.working_dir)}",
            "",
            "system_prompt:",
            prompt,
        ]
    )


def help_text() -> str:
    return """self-edit verbs
  agents | agent <ID>
  tools | tool <name>
  extensions | extension <name>
  skills
  config
  new agent | new tool | new extension
  edit agent <ID> | edit tool <name> | edit extension <name> | edit config
  activate <ID>
  scope project | scope global
  reload
  cancel
  help
  /q"""
