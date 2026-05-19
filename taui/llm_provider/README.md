# LLM Provider Package

This package contains Taui's provider abstraction, provider implementations, model
catalog helpers, and auth flows.

## Code Map

- Base provider contract: `taui/llm_provider/base.py:102`
- Shared stream/result types: `taui/llm_provider/types.py:151`
- Model catalog helpers: `taui/llm_provider/models.py:81`
- Config persistence: `taui/llm_provider/config.py:15`
- GitHub Copilot provider: `taui/llm_provider/providers/copilot.py:33`
- OpenAI Codex provider: `taui/llm_provider/providers/codex.py:26`
- Copilot auth: `taui/llm_provider/auth/copilot.py:214`
- Codex auth: `taui/llm_provider/auth/codex.py:63`

See `docs/providers.md:1` for the maintained provider overview.
