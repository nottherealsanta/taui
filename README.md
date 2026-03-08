# Taui

An agentic coding interface from the future.

## Development

1. Install Python dependencies:
```bash
uv sync
```

2. Install Node.js dependencies:
```bash
npm install
```

3. Build the frontend:
```bash
npm run build
```

4. Run the server:
```bash
uv run taui --path tests/example_project/specs
```

## Architecture

- Single-pane tree-first interface
- Inline Milkdown editor for node content
- CodeMirror code preview in bottom drawer
- xterm terminal in bottom drawer
- Tree folding with localStorage persistence
- Auto-save on editor blur
