pub mod colors;
pub mod registry;
pub mod status_colors;
pub mod syntax;

pub use colors::{ThemeColors, ThemeColorsRefinement};
pub use registry::{
    load_bundled_themes, load_user_themes, Appearance, Theme, ThemeFamily, ThemeRegistry,
    ThemeStyles,
};
pub use status_colors::StatusColors;
pub use syntax::{HighlightStyle, SyntaxTheme};
