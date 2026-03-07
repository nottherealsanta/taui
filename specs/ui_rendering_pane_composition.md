# UI Rendering and Pane Composition

Define requirements for app-shell composition, theme resolution, and spec-tree rendering.

{{status: ready}}

- [specs/ui_rendering_pane_composition.md#ui-rendering-and-pane-composition](ui_rendering_pane_composition.md#ui-rendering-and-pane-composition)
- [Resolve window appearance into active theme](ui_rendering_pane_composition.md#resolve-window-appearance-into-active-theme)
- [Render spec tree rows with caret and depth guides](ui_rendering_pane_composition.md#render-spec-tree-rows-with-caret-and-depth-guides)
- [Render only spec tree pane as primary surface](ui_rendering_pane_composition.md#render-only-spec-tree-pane-as-primary-surface)

## Resolve window appearance into active theme

Map window appearance to dark/light theme selection and sync on appearance changes.

{{status: ready}}

- [specs/ui_rendering_pane_composition.md#resolve-window-appearance-into-active-theme](ui_rendering_pane_composition.md#resolve-window-appearance-into-active-theme)

### Resolve window appearance into active theme leaf
{{status: ready}}

- Appearance changes trigger a theme update and view notification.
{{code_ref: `taui/static/js/app.js`}}
## Render spec tree rows with caret and depth guides

Render indentation guides and inline caret marker for active editing row.

{{status: ready}}

- [specs/ui_rendering_pane_composition.md#render-spec-tree-rows-with-caret-and-depth-guides](ui_rendering_pane_composition.md#render-spec-tree-rows-with-caret-and-depth-guides)

### Render spec tree rows with caret and depth guides leaf
{{status: ready}}

- Caret marker appears at normalized character boundary.
{{code_ref: `taui/static/js/app.js`}}
## Render only spec tree pane as primary surface

Expose a single-pane experience focused on spec tree navigation and editing.

{{status: ready}}

- [specs/ui_rendering_pane_composition.md#render-only-spec-tree-pane-as-primary-surface](ui_rendering_pane_composition.md#render-only-spec-tree-pane-as-primary-surface)

### Render only spec tree pane as primary surface leaf
{{status: ready}}

- Root view renders one spec-tree pane with node selection and inline editing.
{{code_ref: `taui/static/js/app.js`}}
