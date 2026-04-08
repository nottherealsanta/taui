# Taui

An agentic coding interface from the future.

## Development

1. Install Python dependencies:
```bash
uv sync
```

2. Run the backend server:
```bash
uv run taui --path example_project/specs
```

3. Run the Rust GPUI app:
```bash
cargo run --manifest-path ui/Cargo.toml
```
