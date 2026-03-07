# App Shell

Define startup and pane composition for the browser shell.

{{status: in-progress}}

- [specs/ui/app_shell.md#app-shell](app_shell.md#app-shell)
- [Initialize web app shell](app_shell.md#initialize-web-app-shell)
- [Render single-pane composition](app_shell.md#render-single-pane-composition)

## Initialize web app shell

Launch the UI process with initialized shared state for first render.

{{status: in-progress}}

- [specs/ui/app_shell.md#initialize-web-app-shell](app_shell.md#initialize-web-app-shell)

### Initialize web app shell leaf
{{status: in-progress}}

- `uv run taui` starts the server and serves the browser shell.
{{code_ref: `taui/static/js/app.js`}}
{{code_ref: `taui/static/js/app.js`}}
## Render single-pane composition

Compose only the spec tree pane as the primary working surface.

{{status: in-progress}}

- [specs/ui/app_shell.md#render-single-pane-composition](app_shell.md#render-single-pane-composition)

### Render single-pane composition leaf
{{status: in-progress}}

- Spec tree pane remains visible and supports selection plus inline edit.
{{code_ref: `taui/static/js/app.js`}}
{{code_ref: `taui/static/js/app.js`}}
