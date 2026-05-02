# taui

Agentic coding interface you can reshape.

## Install

```bash
uvx taui
```

Or install permanently:

```bash
uv pip install taui
```

## What is taui?

Taui is a highly customizable agentic coding interface. Instead of adapting your workflow to a fixed assistant, you control the interface itself: UI, agent, tools, prompts, and storage.

Taui can run with or without a frontend. Out of the box it ships with three interfaces:

- **CLI** (default) — interactive REPL. This is what starts when you run `taui`.
- **TUI** (opt-in) — Textual terminal UI with panes, scrollable history, visual tool output. Install with `uv pip install taui[tui]`.
- **Web** (opt-in) — FastAPI backend with WebSocket protocol. Install with `uv pip install taui[web]`.

## Requirements

- Python 3.13+
- An LLM API key (set via environment variable or config)

## License

MIT