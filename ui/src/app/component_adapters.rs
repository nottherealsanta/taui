use gpui::*;
use gpui_component::input::{Input, InputState};

use super::state::MetadataEditTarget;
use super::AppShell;
use crate::services::backend_client::CodeRefPreview;

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
        .gap_2()
        .px(px(10.0))
        .py(px(2.0))
        .child(bullet)
        .child(content)
}

// ── Code ref child node ───────────────────────────────────────────────────────

const PREVIEW_HEAD: usize = 5;
const PREVIEW_TAIL: usize = 3;

/// Render a code reference as a child node that looks like a normal tree node.
///
/// - **Normal** (`is_editing = false`): file path as title + code body preview below.
///   Clicking the title activates inline editing.
///   Clicking the code body toggles expand / collapse of the preview.
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
    let element_key: u64 = ((node_id as u64) << 20) | (ref_index as u64);

    let content: gpui::AnyElement = if is_editing {
        if let Some(input_entity) = markdown_input {
            div()
                .flex_1()
                .child(
                    Input::new(input_entity)
                        .appearance(false)
                        .bordered(false)
                        .px(px(0.0))
                        .py(px(0.0))
                        .text_size(crate::app::typography::MARKDOWN_TEXT_SIZE)
                        .font_family(crate::app::typography::CODE_FONT_FAMILY)
                        .line_height(relative(crate::app::typography::MARKDOWN_LINE_HEIGHT)),
                )
                .into_any_element()
        } else {
            let raw_text: SharedString = format!("{{{{code_ref: `{}`}}}}", raw_ref).into();
            div()
                .flex_1()
                .text_size(crate::app::typography::MARKDOWN_TEXT_SIZE)
                .font_family(crate::app::typography::CODE_FONT_FAMILY)
                .text_color(rgb(colors.text_muted))
                .child(raw_text)
                .into_any_element()
        }
    } else {
        render_code_ref_node(
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

    // Same row layout as regular nodes: bullet + content
    let bullet = div()
        .child("•")
        .text_color(rgb(0xc0c0c0))
        .text_size(px(22.0));

    div()
        .id(("code-ref-row", element_key))
        .w_full()
        .flex()
        .flex_row()
        .items_start()
        .gap_2()
        .px(px(10.0))
        .py(px(2.0))
        .child(bullet)
        .child(content)
        .into_any_element()
}

/// Renders a code ref in normal (non-editing) mode, styled like a regular tree node.
/// Title line: file path + line range. Body: code preview (collapsible).
fn render_code_ref_node(
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
    let text_color = rgb(colors.text);
    let muted_color = rgb(colors.text_muted);
    let code_bg = rgb(colors.element_background);      // light gray for code body
    let header_bg = rgb(colors.background);             // white/base background for header
    let ellipsis_bg = rgb(colors.border_variant);       // slightly darker gray for "…" row

    // Build the title: file path + optional line range
    let title_label: SharedString = match preview {
        Some(p) => {
            let path = match workspace_root {
                Some(root) => p
                    .file_path
                    .strip_prefix(root)
                    .unwrap_or(&p.file_path)
                    .trim_start_matches('/')
                    .to_string(),
                None => p.file_path.clone(),
            };
            let range = match (p.line_start, p.line_end) {
                (Some(s), Some(e)) if s == e => format!(" L{}", s),
                (Some(s), Some(e)) => format!(" L{}–L{}", s, e),
                (Some(s), None) => format!(" L{}", s),
                _ => String::new(),
            };
            format!("{}{}", path, range).into()
        }
        None => raw_ref.to_string().into(),
    };

    // Title line — clicking enters inline editing
    let title = div()
        .id(("code-ref-header", element_key))
        .w_full()
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
        .px(px(6.0))
        .py(px(3.0))
        .bg(header_bg)
        .text_xs()
        .font_family(crate::app::typography::CODE_FONT_FAMILY)
        .font_weight(FontWeight::MEDIUM)
        .text_color(text_color)
        .whitespace_normal()
        .child(title_label);

    // Code body preview — clicking toggles expand/collapse
    let code_body: Option<gpui::AnyElement> = preview.and_then(|p| {
        if let Some(err) = &p.error {
            let err_msg: SharedString = format!("error: {}", err).into();
            Some(
                div()
                    .text_xs()
                    .font_family(crate::app::typography::CODE_FONT_FAMILY)
                    .text_color(muted_color)
                    .child(err_msg)
                    .into_any_element(),
            )
        } else if p.content.is_empty() {
            None
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

            Some(
                div()
                    .id(("code-ref-body", element_key))
                    .mt(px(2.0))
                    .px(px(6.0))
                    .py(px(4.0))
                    .bg(code_bg)
                    .rounded(px(3.0))
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
                    .flex()
                    .flex_col()
                    .children(display_lines.into_iter().map(|line| {
                        let is_ellipsis = line.as_ref() == "…";
                        if is_ellipsis {
                            div()
                                .w_full()
                                .py(px(1.0))
                                .bg(ellipsis_bg)
                                .rounded(px(2.0))
                                .text_xs()
                                .text_color(muted_color)
                                .font_family(crate::app::typography::CODE_FONT_FAMILY)
                                .text_align(gpui::TextAlign::Center)
                                .child(line)
                        } else {
                            div()
                                .text_xs()
                                .font_family(crate::app::typography::CODE_FONT_FAMILY)
                                .text_color(text_color)
                                .child(if line.as_ref().is_empty() {
                                    SharedString::from(" ".to_string())
                                } else {
                                    line
                                })
                        }
                    }))
                    .into_any_element(),
            )
        }
    });

    // Normal node layout: title + optional body below, with a subtle border
    div()
        .flex_1()
        .min_w_0()
        .flex()
        .flex_col()
        .border_1()
        .border_color(rgb(colors.border_variant))
        .rounded(px(6.0))
        .overflow_hidden()
        .child(title)
        .children(code_body)
        .into_any_element()
}
