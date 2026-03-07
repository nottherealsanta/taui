# Taui Web UI Plan

## Goal

Replace the Rust/GPUI desktop app with a browser UI served by `uv run taui`.

## Decisions

- Keep backend protocol: WebSocket + JSON-RPC 2.0.
- Serve static UI from Python package (`taui/static/*`).
- No framework and no Tailwind build pipeline.
- Single-pane UI: spec tree only.

## Delivery Scope

1. Remove `ui/` Rust crate and Cargo artifacts.
2. Replace CLI REPL entrypoint with web server launcher.
3. Mount static assets in FastAPI and serve `/`.
4. Implement plain JS client for connect/initialize/spec tree rendering/update.
5. Update specs/docs/tests to point at web implementation.
