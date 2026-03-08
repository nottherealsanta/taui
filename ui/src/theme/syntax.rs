#[derive(Clone, Debug, Default)]
pub struct HighlightStyle {
    pub color: Option<u32>,
    pub background_color: Option<u32>,
    pub italic: Option<bool>,
    pub bold: Option<bool>,
}

#[derive(Clone, Debug, Default)]
pub struct SyntaxTheme {
    pub highlights: Vec<(String, HighlightStyle)>,
}
