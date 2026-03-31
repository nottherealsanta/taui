from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
import tomllib
from typing import Any


DEFAULT_CONFIG_PATH = Path.home() / ".config" / "taui" / "config.toml"


@dataclass(slots=True)
class ProviderSettings:
    api_key_env: str | None = None
    api_key: str | None = None


@dataclass(slots=True)
class ModelSettings:
    default: str = "copilot:claude-sonnet-4.6"


@dataclass(slots=True)
class PolicySettings:
    auto_approve: tuple[str, ...] = ("read", "glob", "grep")
    confirm: tuple[str, ...] = ("edit", "write", "bash")
    deny: tuple[str, ...] = ()


@dataclass(slots=True)
class BashPolicySettings:
    restrict_workdir_to_workspace: bool = True
    allow_network: bool = True
    env_allowlist: tuple[str, ...] = ("PATH", "HOME", "TERM")
    max_output_bytes: int = 51_200
    default_timeout_sec: int = 120


@dataclass(slots=True)
class McpServerSettings:
    command: str = ""
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True


@dataclass(slots=True)
class Settings:
    model: ModelSettings = field(default_factory=ModelSettings)
    providers: dict[str, ProviderSettings] = field(default_factory=dict)
    policy: PolicySettings = field(default_factory=PolicySettings)
    policy_bash: BashPolicySettings = field(default_factory=BashPolicySettings)
    mcp_servers: dict[str, McpServerSettings] = field(default_factory=dict)

    def provider(self, name: str) -> ProviderSettings:
        return self.providers.setdefault(name, ProviderSettings())


def load_settings(
    config_path: Path | None = None, overrides: dict[str, Any] | None = None
) -> Settings:
    data = _read_config(config_path or DEFAULT_CONFIG_PATH)
    settings = _from_mapping(data)
    _apply_env(settings)
    if overrides:
        _apply_overrides(settings, overrides)
    return settings


def _read_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        parsed = tomllib.load(handle)
    if not isinstance(parsed, dict):
        raise ValueError("Invalid config: expected a top-level table.")
    return parsed


def _from_mapping(data: dict[str, Any]) -> Settings:
    settings = Settings()

    model_table = _as_dict(data.get("model"), "model")
    default_model = model_table.get("default")
    if isinstance(default_model, str) and default_model:
        settings.model.default = default_model

    providers_table = _as_dict(data.get("providers"), "providers")
    for provider_name, provider_table_raw in providers_table.items():
        provider_table = _as_dict(provider_table_raw, f"providers.{provider_name}")
        provider = ProviderSettings()
        api_key_env = provider_table.get("api_key_env")
        if api_key_env is not None and not isinstance(api_key_env, str):
            raise ValueError(
                f"Invalid providers.{provider_name}.api_key_env: expected string."
            )
        provider.api_key_env = api_key_env
        settings.providers[provider_name] = provider

    policy_table = _as_dict(data.get("policy"), "policy")
    settings.policy = PolicySettings(
        auto_approve=_as_string_tuple(
            policy_table.get("auto_approve"),
            "policy.auto_approve",
            settings.policy.auto_approve,
        ),
        confirm=_as_string_tuple(
            policy_table.get("confirm"), "policy.confirm", settings.policy.confirm
        ),
        deny=_as_string_tuple(
            policy_table.get("deny"), "policy.deny", settings.policy.deny
        ),
    )

    bash_table = _as_dict(policy_table.get("bash"), "policy.bash")
    settings.policy_bash = BashPolicySettings(
        restrict_workdir_to_workspace=_as_bool(
            bash_table.get("restrict_workdir_to_workspace"),
            "policy.bash.restrict_workdir_to_workspace",
            settings.policy_bash.restrict_workdir_to_workspace,
        ),
        allow_network=_as_bool(
            bash_table.get("allow_network"),
            "policy.bash.allow_network",
            settings.policy_bash.allow_network,
        ),
        env_allowlist=_as_string_tuple(
            bash_table.get("env_allowlist"),
            "policy.bash.env_allowlist",
            settings.policy_bash.env_allowlist,
        ),
        max_output_bytes=_as_int(
            bash_table.get("max_output_bytes"),
            "policy.bash.max_output_bytes",
            settings.policy_bash.max_output_bytes,
        ),
        default_timeout_sec=_as_int(
            bash_table.get("default_timeout_sec"),
            "policy.bash.default_timeout_sec",
            settings.policy_bash.default_timeout_sec,
        ),
    )

    mcp_table = _as_dict(data.get("mcp_servers"), "mcp_servers")
    for server_name, server_raw in mcp_table.items():
        server_table = _as_dict(server_raw, f"mcp_servers.{server_name}")
        command = server_table.get("command", "")
        if not isinstance(command, str):
            raise ValueError(f"Invalid mcp_servers.{server_name}.command: expected string.")
        args_raw = server_table.get("args", [])
        if not isinstance(args_raw, list) or not all(isinstance(a, str) for a in args_raw):
            raise ValueError(f"Invalid mcp_servers.{server_name}.args: expected array of strings.")
        env_raw = server_table.get("env", {})
        if not isinstance(env_raw, dict):
            raise ValueError(f"Invalid mcp_servers.{server_name}.env: expected table.")
        env = {k: v for k, v in env_raw.items() if isinstance(k, str) and isinstance(v, str)}
        enabled = server_table.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError(f"Invalid mcp_servers.{server_name}.enabled: expected boolean.")
        settings.mcp_servers[server_name] = McpServerSettings(
            command=command,
            args=tuple(args_raw),
            env=env,
            enabled=enabled,
        )

    return settings


def _apply_env(settings: Settings) -> None:
    for provider in settings.providers.values():
        if provider.api_key_env:
            provider.api_key = os.getenv(provider.api_key_env)


def _apply_overrides(settings: Settings, overrides: dict[str, Any]) -> None:
    model_default = overrides.get("model.default")
    if isinstance(model_default, str) and model_default:
        settings.model.default = model_default

    provider_overrides = overrides.get("providers")
    if isinstance(provider_overrides, dict):
        for provider_name, provider_data in provider_overrides.items():
            if not isinstance(provider_data, dict):
                continue
            provider = settings.provider(str(provider_name))
            api_key = provider_data.get("api_key")
            if isinstance(api_key, str) and api_key:
                provider.api_key = api_key


def _as_dict(value: Any, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"Invalid {field_name}: expected table.")
    return value


def _as_string_tuple(
    value: Any, field_name: str, default: tuple[str, ...]
) -> tuple[str, ...]:
    if value is None:
        return default
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"Invalid {field_name}: expected array of strings.")
    return tuple(value)


def _as_bool(value: Any, field_name: str, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValueError(f"Invalid {field_name}: expected boolean.")
    return value


def _as_int(value: Any, field_name: str, default: int) -> int:
    if value is None:
        return default
    if not isinstance(value, int):
        raise ValueError(f"Invalid {field_name}: expected integer.")
    return value
