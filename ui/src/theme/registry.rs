use std::path::Path;

use super::{StatusColors, SyntaxTheme, ThemeColors};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Appearance {
    Light,
    Dark,
}

#[derive(Clone, Debug)]
pub struct ThemeStyles {
    pub colors: ThemeColors,
    pub status: StatusColors,
    pub syntax: SyntaxTheme,
}

#[derive(Clone, Debug)]
pub struct Theme {
    pub name: String,
    pub appearance: Appearance,
    pub styles: ThemeStyles,
}

#[derive(Clone, Debug)]
pub struct ThemeFamily {
    pub name: String,
    pub author: String,
    pub themes: Vec<Theme>,
}

#[derive(Clone, Debug)]
pub struct ThemeRegistry {
    pub families: Vec<ThemeFamily>,
}

impl ThemeRegistry {
    pub fn new() -> Self {
        Self {
            families: load_bundled_themes(),
        }
    }

    pub fn default_dark(&self) -> Option<Theme> {
        if let Some(one_dark) = self
            .families
            .iter()
            .flat_map(|family| family.themes.iter())
            .find(|theme| {
                theme.appearance == Appearance::Dark
                    && theme.name.to_ascii_lowercase().contains("one dark")
            })
        {
            return Some(one_dark.clone());
        }

        self.families
            .iter()
            .flat_map(|family| family.themes.iter())
            .find(|theme| theme.appearance == Appearance::Dark)
            .cloned()
    }
}

pub fn load_bundled_themes() -> Vec<ThemeFamily> {
    let taui_family = ThemeFamily {
        name: "Taui".to_string(),
        author: "Taui".to_string(),
        themes: vec![
            Theme {
                name: "Taui Dark".to_string(),
                appearance: Appearance::Dark,
                styles: ThemeStyles {
                    colors: ThemeColors::taui_dark(),
                    status: StatusColors::taui_dark(),
                    syntax: SyntaxTheme::default(),
                },
            },
            Theme {
                name: "Taui Light".to_string(),
                appearance: Appearance::Light,
                styles: ThemeStyles {
                    colors: ThemeColors::taui_light(),
                    status: StatusColors::taui_light(),
                    syntax: SyntaxTheme::default(),
                },
            },
        ],
    };

    let zed_like = ThemeFamily {
        name: "Zed One".to_string(),
        author: "Taui".to_string(),
        themes: vec![Theme {
            name: "Zed One Dark".to_string(),
            appearance: Appearance::Dark,
            styles: ThemeStyles {
                colors: ThemeColors {
                    background: 0x0f1419,
                    panel_background: 0x18212b,
                    elevated_surface_background: 0x1d2a37,
                    border: 0x2f3e50,
                    border_variant: 0x233041,
                    text: 0xe8edf2,
                    text_muted: 0x9baec2,
                    text_accent: 0x7ac8ff,
                    element_background: 0x202d3c,
                    element_hover: 0x2a3b4f,
                    element_selected: 0x31506f,
                },
                status: StatusColors::taui_dark(),
                syntax: SyntaxTheme::default(),
            },
        }],
    };

    vec![taui_family, zed_like]
}

pub fn load_user_themes(path: &Path) -> Vec<ThemeFamily> {
    if !path.exists() {
        return Vec::new();
    }

    // JSON loading is intentionally deferred; first milestone only checks for path presence.
    Vec::new()
}
