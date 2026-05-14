# LLM Provider

This folder contains the LLM provider base class, provider implementations, and test scripts.

## Files

- `base.py` — `BaseLLMProvider` abstract base class with retry, streaming, error handling
- `types.py` — Shared types: `StreamEvent`, `ProviderTurnResult`, `ProviderCapabilities`, etc.

The interactive probe script lives at `scripts/provider_probe.py` (at the repo
root, outside the installed package).

## Usage

```bash
# Probe a provider's capabilities
uv run python scripts/provider_probe.py copilot
uv run python scripts/provider_probe.py codex

# Run with specific tests
uv run python scripts/provider_probe.py copilot --test streaming
uv run python scripts/provider_probe.py copilot --test tools
uv run python scripts/provider_probe.py copilot --test reasoning
```

## Documentation

See [../../docs/_/llm-provider.md](../../docs/_/llm-provider.md) for the full design document.
