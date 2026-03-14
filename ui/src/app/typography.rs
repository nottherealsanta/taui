use gpui::{px, rems, FontWeight, Pixels};
use gpui_component::highlighter::HighlightTheme;
use gpui_component::text::TextViewStyle;

pub const MAX_CONTENT_WIDTH: Pixels = px(820.0);
pub const INDENT_PER_LEVEL: Pixels = px(24.0);
pub const MARKDOWN_TEXT_SIZE: Pixels = px(16.0);
pub const MARKDOWN_LINE_HEIGHT: f32 = 1.45;

pub const BODY_FONT_FAMILY: &str = "IBM Plex Sans";
pub const CODE_FONT_FAMILY: &str = "JetBrains Mono";

pub struct HeadingStyle {
    pub font_size: Pixels,
    pub font_weight: FontWeight,
}

pub struct ContentStyle {
    pub font_size: Pixels,
    pub font_weight: FontWeight,
    pub line_height_value: f32,
    pub font_family: &'static str,
}

pub fn depth_to_heading_style(depth: usize) -> HeadingStyle {
    match depth {
        0 => HeadingStyle {
            font_size: px(16.0),
            font_weight: FontWeight::NORMAL,
        },
        1 => HeadingStyle {
            font_size: px(22.0),
            font_weight: FontWeight::SEMIBOLD,
        },
        2 => HeadingStyle {
            font_size: px(18.0),
            font_weight: FontWeight::MEDIUM,
        },
        _ => HeadingStyle {
            font_size: MARKDOWN_TEXT_SIZE,
            font_weight: FontWeight::NORMAL,
        },
    }
}

pub fn content_style() -> ContentStyle {
    ContentStyle {
        font_size: MARKDOWN_TEXT_SIZE,
        font_weight: FontWeight::NORMAL,
        line_height_value: MARKDOWN_LINE_HEIGHT,
        font_family: CODE_FONT_FAMILY,
    }
}

pub fn markdown_view_style(is_dark: bool) -> TextViewStyle {
    let highlight_theme = if is_dark {
        HighlightTheme::default_dark()
    } else {
        HighlightTheme::default_light()
    };

    TextViewStyle {
        paragraph_gap: rems(0.45),
        heading_base_font_size: MARKDOWN_TEXT_SIZE,
        heading_font_size: Some(std::sync::Arc::new(|level, _base| match level {
            1 => px(19.0),
            2 => px(18.0),
            3 => px(17.0),
            4 => px(16.5),
            _ => MARKDOWN_TEXT_SIZE,
        })),
        highlight_theme,
        code_block: Default::default(),
        is_dark,
    }
}

pub fn markdown_edit_style(_markdown: &str) -> (Pixels, FontWeight) {
    // The editor can only apply one style to the full buffer. Keeping a stable body
    // style avoids large visual jumps when toggling between read and edit modes.
    (MARKDOWN_TEXT_SIZE, FontWeight::NORMAL)
}

pub fn split_content_lines(content: &str) -> Vec<&str> {
    if content.is_empty() {
        Vec::new()
    } else {
        content.split('\n').collect()
    }
}

/// Splits root markdown into (title, body) where title is the first non-empty line
/// with markdown heading markers stripped.
pub fn split_root_markdown(markdown: &str) -> (String, String) {
    let lines: Vec<&str> = markdown.lines().collect();
    let mut title = String::new();
    let mut body_start = 0;

    for (i, line) in lines.iter().enumerate() {
        let trimmed = line.trim();
        if !trimmed.is_empty() {
            // Strip leading markdown heading markers (#, ##, ###, etc.)
            title = trimmed.trim_start_matches('#').trim_start().to_string();
            body_start = i + 1;
            break;
        }
    }

    // Collect remaining lines for body
    let body: String = lines[body_start..]
        .iter()
        .copied()
        .collect::<Vec<_>>()
        .join("\n");

    (title, body)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_depth_0_is_h1() {
        let style = depth_to_heading_style(0);
        assert_eq!(style.font_size, px(16.0));
        assert_eq!(style.font_weight, FontWeight::NORMAL);
    }

    #[test]
    fn test_depth_1_is_h2() {
        let style = depth_to_heading_style(1);
        assert_eq!(style.font_size, px(22.0));
        assert_eq!(style.font_weight, FontWeight::SEMIBOLD);
    }

    #[test]
    fn test_depth_2_is_h3() {
        let style = depth_to_heading_style(2);
        assert_eq!(style.font_size, px(18.0));
        assert_eq!(style.font_weight, FontWeight::MEDIUM);
    }

    #[test]
    fn test_depth_3_is_h4() {
        let style = depth_to_heading_style(3);
        assert_eq!(style.font_size, MARKDOWN_TEXT_SIZE);
        assert_eq!(style.font_weight, FontWeight::NORMAL);
    }

    #[test]
    fn test_depth_4_is_h5() {
        let style = depth_to_heading_style(4);
        assert_eq!(style.font_size, MARKDOWN_TEXT_SIZE);
        assert_eq!(style.font_weight, FontWeight::NORMAL);
    }

    #[test]
    fn test_depth_5_and_beyond_is_h6() {
        for depth in 5..10 {
            let style = depth_to_heading_style(depth);
            assert_eq!(style.font_size, MARKDOWN_TEXT_SIZE);
            assert_eq!(style.font_weight, FontWeight::NORMAL);
        }
    }

    #[test]
    fn test_split_content_lines_empty() {
        let lines = split_content_lines("");
        assert!(lines.is_empty());
    }

    #[test]
    fn test_split_content_lines_single() {
        let lines = split_content_lines("Hello world");
        assert_eq!(lines, vec!["Hello world"]);
    }

    #[test]
    fn test_split_content_lines_multiple() {
        let lines = split_content_lines("Line 1\nLine 2\nLine 3");
        assert_eq!(lines, vec!["Line 1", "Line 2", "Line 3"]);
    }

    #[test]
    fn test_content_style_consistency() {
        let style = content_style();
        assert_eq!(style.font_size, MARKDOWN_TEXT_SIZE);
        assert_eq!(style.font_weight, FontWeight::NORMAL);
        assert_eq!(style.line_height_value, MARKDOWN_LINE_HEIGHT);
        assert_eq!(style.font_family, CODE_FONT_FAMILY);
    }

    #[test]
    fn test_content_style_parity_with_markdown_render() {
        let style = content_style();
        assert_eq!(
            style.font_size, MARKDOWN_TEXT_SIZE,
            "content font size should match markdown render"
        );
        assert_eq!(
            style.line_height_value, MARKDOWN_LINE_HEIGHT,
            "content line height should match markdown render"
        );
    }

    #[test]
    fn test_depth_0_heading_matches_read_mode() {
        let style = depth_to_heading_style(0);
        assert_eq!(style.font_size, px(16.0));
        assert_eq!(style.font_weight, FontWeight::NORMAL);
    }

    #[test]
    fn test_markdown_edit_style_is_stable_for_headings() {
        let (font_size, font_weight) = markdown_edit_style("### Heading\nBody text");
        assert_eq!(font_size, MARKDOWN_TEXT_SIZE);
        assert_eq!(font_weight, FontWeight::NORMAL);
    }

    #[test]
    fn test_heading_styles_decrease_from_depth_1() {
        let mut prev_size = px(100.0);
        for depth in 1..=6 {
            let style = depth_to_heading_style(depth);
            assert!(
                style.font_size <= prev_size,
                "Heading font size should decrease or stay same as depth increases (depth {})",
                depth
            );
            prev_size = style.font_size;
        }
    }

    #[test]
    fn test_split_root_markdown_basic() {
        let markdown = "Title\nBody line 1\nBody line 2";
        let (title, body) = split_root_markdown(markdown);
        assert_eq!(title, "Title");
        assert_eq!(body, "Body line 1\nBody line 2");
    }

    #[test]
    fn test_split_root_markdown_with_heading_prefix() {
        let markdown = "# Heading Title\nBody content";
        let (title, body) = split_root_markdown(markdown);
        assert_eq!(title, "Heading Title");
        assert_eq!(body, "Body content");
    }

    #[test]
    fn test_split_root_markdown_with_multiple_heading_prefixes() {
        let markdown = "### Deep Heading\nBody";
        let (title, body) = split_root_markdown(markdown);
        assert_eq!(title, "Deep Heading");
        assert_eq!(body, "Body");
    }

    #[test]
    fn test_split_root_markdown_empty() {
        let markdown = "";
        let (title, body) = split_root_markdown(markdown);
        assert_eq!(title, "");
        assert_eq!(body, "");
    }

    #[test]
    fn test_split_root_markdown_only_title() {
        let markdown = "Only Title";
        let (title, body) = split_root_markdown(markdown);
        assert_eq!(title, "Only Title");
        assert_eq!(body, "");
    }

    #[test]
    fn test_split_root_markdown_with_leading_whitespace() {
        let markdown = "\n\n  # Title with space  \nBody";
        let (title, body) = split_root_markdown(markdown);
        assert_eq!(title, "Title with space");
        assert_eq!(body, "Body");
    }

    #[test]
    fn test_split_root_markdown_title_only_with_heading() {
        let markdown = "## Title Only";
        let (title, body) = split_root_markdown(markdown);
        assert_eq!(title, "Title Only");
        assert_eq!(body, "");
    }
}
