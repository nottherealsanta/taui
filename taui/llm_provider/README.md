# LLM Provider

This folder contains the LLM provider base class, provider implementations, and test scripts.

## Files

- `base.py` — `BaseLLMProvider` abstract base class with retry, streaming, error handling
- `types.py` — Shared types: `StreamEvent`, `ProviderTurnResult`, `ProviderCapabilities`, etc.
- `provider_probe.py` — Interactive script to test provider features (streaming, tools, reasoning)

## Usage

```bash
# Probe a provider's capabilities
python -m taui.llm_provider.provider_probe copilot
python -m taui.llm_provider.provider_probe codex
python -m taui.llm_provider.provider_probe openai

# Run with specific tests
python -m taui.llm_provider.provider_probe copilot --test streaming
python -m taui.llm_provider.provider_probe copilot --test tools
python -m taui.llm_provider.provider_probe copilot --test reasoning
```

## Documentation

See [../../docs/_/llm-provider.md](../../docs/_/llm-provider.md) for the full design document.
