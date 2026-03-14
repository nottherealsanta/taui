use gpui::*;
use gpui_component::button::{Button, ButtonVariants};
use gpui_component::input::{Input, InputState};
use gpui_component::Sizable;

use super::actions::UiAction;
use super::state::MetadataEditTarget;
use super::AppShell;
use crate::services::backend_client::CodeRefPreview;

pub fn render_chevron(
    collapsed: bool,
    has_children: bool,
    is_root: bool,
    node_id: crate::app::state::NodeId,
    cx: &mut Context<AppShell>,
) -> Option<gpui::AnyElement> {
    if !has_children || is_root {
        return None;
    }

    let chevron_icon = if collapsed { "▶" } else { "▼" };

    let button = Button::new(("chevron", node_id))
        .child(chevron_icon)
        .xsmall()
        .ghost()
        .text_color(gpui::rgb(0x9CA3AF)) // Light gray
        .on_mouse_down(
            MouseButton::Left,
            cx.listener(move |this, _event, _window, cx| {
                this.apply(UiAction::SelectNode(node_id), cx);
                this.apply(UiAction::ToggleCollapse, cx);
            }),
        );

    Some(button.into_any_element())
}

// ── Shared bullet row layout ──────────────────────────────────────────────────

/// Renders a bullet + content row (no chevron), used for metadata child nodes.
fn meta_bullet(colors: &crate::theme::ThemeColors) -> gpui::AnyElement {
    div()
        .child("•")
        .text_color(rgb(colors.text_muted))
        .text_size(px(22.0))
        .into_any_element()
}

// ── Metadata child node (verification / depends_on / related_to) ─────────────

/// Render a raw `{{key: value}}` metadata item as a bullet child node.
///
/// - In view mode: shows the raw string as clickable monospace text.
///   Clicking calls `on_click` to activate inline editing.
/// - In editing mode (`is_editing = true`): shows the shared `markdown_input`
///   as an inline `Input` widget.
///
/// `element_key` must be unique across all metadata children in the tree so
/// GPUI can correctly identify interactive elements.
pub fn render_metadata_child(
    text: SharedString,
    colors: &crate::theme::ThemeColors,
    is_editing: bool,
    markdown_input: Option<&Entity<InputState>>,
    element_key: u64,
    on_click: impl Fn(&mut AppShell, &mut Window, &mut Context<AppShell>) + 'static,
    cx: &mut Context<AppShell>,
) -> impl IntoElement {
    let bullet = meta_bullet(colors);
    let text_color = rgb(colors.text_muted);

    let content: gpui::AnyElement = if is_editing {
        if let Some(input_entity) = markdown_input {
            div()
                .flex_1()
                .pt(px(3.0))
                .child(
                    Input::new(input_entity)
                        .appearance(false)
                        .bordered(false)
                        .px(px(0.0))
                        .py(px(0.0))
                        .text_sm()
                        .font_family(crate::app::typography::CODE_FONT_FAMILY),
                )
                .into_any_element()
        } else {
            // Fallback: show text statically (shouldn't happen in practice)
            div()
                .flex_1()
                .text_sm()
                .font_family(crate::app::typography::CODE_FONT_FAMILY)
                .text_color(text_color)
                .pt(px(3.0))
                .child(text)
                .into_any_element()
        }
    } else {
        div()
            .id(("meta-child", element_key))
            .flex_1()
            .cursor_pointer()
            .text_sm()
            .font_family(crate::app::typography::CODE_FONT_FAMILY)
            .text_color(text_color)
            .pt(px(3.0))
            .on_mouse_down(
                MouseButton::Left,
                cx.listener(move |this, _event, window, cx| {
                    on_click(this, window, cx);
                }),
            )
            .child(text)
            .into_any_element()
    };

    div()
        .id(("meta-row", element_key))
        .w_full()
        .flex()
        .flex_row()
        .items_start()
        .gap_1()
        .px(px(10.0))
        .py(px(2.0))
        .child(
            // spacer matching the invisible chevron slot width
            div().w(px(24.0)),
        )
        .child(bullet)
        .child(content)
}

// ── Code ref child node ───────────────────────────────────────────────────────

const PREVIEW_HEAD: usize = 5;
const PREVIEW_TAIL: usize = 3;

/// Render a code reference as a bullet child node.
///
/// Two states:
/// - **Normal** (`is_editing = false`): rich card — file path header + code body preview.
///   Clicking the header activates inline editing.
///   Clicking the code body toggles expand / collapse.
/// - **Editing** (`is_editing = true`): shows the shared `markdown_input` as an inline
///   `Input` pre-filled with `{{code_ref: \`raw_ref\`}}`. Blur/save returns to normal.
pub fn render_code_ref_child(
    raw_ref: &str,
    preview: Option<&CodeRefPreview>,
    node_id: crate::app::state::NodeId,
    ref_index: usize,
    is_expanded: bool,
    is_editing: bool,
    markdown_input: Option<&Entity<InputState>>,
    workspace_root: Option<&str>,
    colors: &crate::theme::ThemeColors,
    cx: &mut Context<AppShell>,
) -> gpui::AnyElement {
    let bullet = meta_bullet(colors);

    // Encode node_id + ref_index into a u64 key for ElementId uniqueness.
    let element_key: u64 = ((node_id as u64) << 20) | (ref_index as u64);

    let content: gpui::AnyElement = if is_editing {
        // ── Editing mode: inline Input ────────────────────────────────────────
        if let Some(input_entity) = markdown_input {
            div()
                .flex_1()
                .pt(px(3.0))
                .child(
                    Input::new(input_entity)
                        .appearance(false)
                        .bordered(false)
                        .px(px(0.0))
                        .py(px(0.0))
                        .text_sm()
                        .font_family(crate::app::typography::CODE_FONT_FAMILY),
                )
                .into_any_element()
        } else {
            // Fallback (shouldn't happen)
            let raw_text: SharedString = format!("{{{{code_ref: `{}`}}}}", raw_ref).into();
            div()
                .flex_1()
                .text_sm()
                .font_family(crate::app::typography::CODE_FONT_FAMILY)
                .text_color(rgb(colors.text_muted))
                .pt(px(3.0))
                .child(raw_text)
                .into_any_element()
        }
    } else {
        // ── Normal mode: rich card ────────────────────────────────────────────
        render_code_ref_rich(
            raw_ref,
            preview,
            node_id,
            ref_index,
            is_expanded,
            element_key,
            workspace_root,
            colors,
            cx,
        )
    };

    div()
        .id(("code-ref-row", element_key))
        .w_full()
        .flex()
        .flex_row()
        .items_start()
        .gap_1()
        .px(px(10.0))
        .py(px(2.0))
        .child(
            // spacer matching the invisible chevron slot width
            div().w(px(24.0)),
        )
        .child(bullet)
        .child(content)
        .into_any_element()
}

/// Renders the rich code-ref card (header + optional code body).
fn render_code_ref_rich(
    raw_ref: &str,
    preview: Option<&CodeRefPreview>,
    node_id: crate::app::state::NodeId,
    ref_index: usize,
    is_expanded: bool,
    element_key: u64,
    workspace_root: Option<&str>,
    colors: &crate::theme::ThemeColors,
    cx: &mut Context<AppShell>,
) -> gpui::AnyElement {
    let header_bg = rgb(colors.element_background);
    let header_text = rgb(colors.text_muted);
    let border_color = rgb(colors.border_variant);
    let code_bg = rgb(colors.background);
    let code_text = rgb(colors.text);

    // ── header: file path  L{start}–L{end} ───────────────────────────────────
    let (path_label, range_label): (SharedString, SharedString) = match preview {
        Some(p) => {
            let path: SharedString = match workspace_root {
                Some(root) => p
                    .file_path
                    .strip_prefix(root)
                    .unwrap_or(&p.file_path)
                    .trim_start_matches('/')
                    .to_string()
                    .into(),
                None => p.file_path.clone().into(),
            };
            let range: SharedString = match (p.line_start, p.line_end) {
                (Some(s), Some(e)) if s == e => format!("L{}", s).into(),
                (Some(s), Some(e)) => format!("L{}–L{}", s, e).into(),
                (Some(s), None) => format!("L{}", s).into(),
                _ => String::new().into(),
            };
            (path, range)
        }
        None => (raw_ref.to_string().into(), String::new().into()),
    };

    // Clicking the header enters inline editing for this code_ref.
    let header = div()
        .id(("code-ref-header", element_key))
        .w_full()
        .flex()
        .items_center()
        .justify_between()
        .px(px(8.0))
        .py(px(4.0))
        .bg(header_bg)
        .cursor_pointer()
        .on_mouse_down(
            MouseButton::Left,
            cx.listener(move |this, _event, window, cx| {
                this.select_metadata_item(
                    MetadataEditTarget::CodeRef { node_id, ref_index },
                    window,
                    cx,
                );
            }),
        )
        .child(
            div()
                .text_xs()
                .font_weight(FontWeight::MEDIUM)
                .text_color(header_text)
                .child(path_label),
        )
        .child(div().text_xs().text_color(header_text).child(range_label));

    // ── code body — clicking toggles expand/collapse ──────────────────────────
    let code_body: Option<gpui::AnyElement> = preview.map(|p| {
        let body: gpui::AnyElement = if let Some(err) = &p.error {
            let err_msg: SharedString = format!("error: {}", err).into();
            div()
                .w_full()
                .px(px(8.0))
                .py(px(6.0))
                .bg(code_bg)
                .text_xs()
                .font_family(crate::app::typography::CODE_FONT_FAMILY)
                .text_color(rgb(colors.text_muted))
                .child(err_msg)
                .into_any_element()
        } else {
            let all_lines: Vec<&str> = p.content.lines().collect();
            let total = all_lines.len();

            let display_lines: Vec<SharedString> =
                if is_expanded || total <= PREVIEW_HEAD + PREVIEW_TAIL {
                    all_lines
                        .iter()
                        .map(|l| SharedString::from(l.to_string()))
                        .collect()
                } else {
                    let mut lines: Vec<SharedString> = all_lines[..PREVIEW_HEAD]
                        .iter()
                        .map(|l| SharedString::from(l.to_string()))
                        .collect();
                    lines.push(SharedString::from("…".to_string()));
                    lines.extend(
                        all_lines[total - PREVIEW_TAIL..]
                            .iter()
                            .map(|l| SharedString::from(l.to_string())),
                    );
                    lines
                };

            div()
                .w_full()
                .px(px(8.0))
                .py(px(6.0))
                .bg(code_bg)
                .flex()
                .flex_col()
                .children(display_lines.into_iter().map(|line| {
                    let is_ellipsis = line.as_ref() == "…";
                    div()
                        .text_xs()
                        .font_family(crate::app::typography::CODE_FONT_FAMILY)
                        .text_color(if is_ellipsis {
                            rgb(colors.text_muted)
                        } else {
                            code_text
                        })
                        .child(if line.as_ref().is_empty() {
                            SharedString::from(" ".to_string())
                        } else {
                            line
                        })
                }))
                .into_any_element()
        };

        // Clicking the code body toggles expand/collapse.
        div()
            .id(("code-ref-body", element_key))
            .w_full()
            .border_t_1()
            .border_color(border_color)
            .cursor_pointer()
            .on_mouse_down(
                MouseButton::Left,
                cx.listener(move |this, _event, _window, cx| {
                    let key = (node_id, ref_index);
                    if this.expanded_code_refs.contains(&key) {
                        this.expanded_code_refs.remove(&key);
                    } else {
                        this.expanded_code_refs.insert(key);
                    }
                    cx.notify();
                }),
            )
            .child(body)
            .into_any_element()
    });

    // ── outer card wrapper ────────────────────────────────────────────────────
    div()
        .flex_1()
        .mt(px(2.0))
        .mb(px(2.0))
        .rounded(px(4.0))
        .border_1()
        .border_color(border_color)
        .overflow_hidden()
        .flex()
        .flex_col()
        .child(header)
        .children(code_body)
        .into_any_element()
}
