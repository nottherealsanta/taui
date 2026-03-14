#[derive(Clone, Copy, Debug)]
pub struct ThemeColors {
    pub background: u32,
    pub panel_background: u32,
    pub elevated_surface_background: u32,
    pub border: u32,
    pub border_variant: u32,
    pub text: u32,
    pub text_muted: u32,
    pub text_accent: u32,
    pub element_background: u32,
    pub element_hover: u32,
    pub element_selected: u32,
}

#[derive(Clone, Copy, Debug, Default)]
pub struct ThemeColorsRefinement {
    pub background: Option<u32>,
    pub panel_background: Option<u32>,
    pub elevated_surface_background: Option<u32>,
    pub border: Option<u32>,
    pub border_variant: Option<u32>,
    pub text: Option<u32>,
    pub text_muted: Option<u32>,
    pub text_accent: Option<u32>,
    pub element_background: Option<u32>,
    pub element_hover: Option<u32>,
    pub element_selected: Option<u32>,
}

impl ThemeColors {
    pub fn taui_dark() -> Self {
        Self {
            background: 0x000000,
            panel_background: 0x121822,
            elevated_surface_background: 0x1b2432,
            border: 0x2d3749,
            border_variant: 0x1f2735,
            text: 0xe6edf3,
            text_muted: 0x9fb0c2,
            text_accent: 0x7cc7ff,
            element_background: 0x1d2532,
            element_hover: 0x243144,
            element_selected: 0x2d3f59,
        }
    }

    pub fn taui_light() -> Self {
        Self {
            background: 0xf5f7fb,
            panel_background: 0xffffff,
            elevated_surface_background: 0xebf0f8,
            border: 0xd8e1ee,
            border_variant: 0xe6edf7,
            text: 0x1a2433,
            text_muted: 0x5e7288,
            text_accent: 0x0d6bcf,
            element_background: 0xf0f4fa,
            element_hover: 0xe5edf8,
            element_selected: 0xd9e7fb,
        }
    }

    pub fn refine(&mut self, refinement: &ThemeColorsRefinement) {
        if let Some(v) = refinement.background {
            self.background = v;
        }
        if let Some(v) = refinement.panel_background {
            self.panel_background = v;
        }
        if let Some(v) = refinement.elevated_surface_background {
            self.elevated_surface_background = v;
        }
        if let Some(v) = refinement.border {
            self.border = v;
        }
        if let Some(v) = refinement.border_variant {
            self.border_variant = v;
        }
        if let Some(v) = refinement.text {
            self.text = v;
        }
        if let Some(v) = refinement.text_muted {
            self.text_muted = v;
        }
        if let Some(v) = refinement.text_accent {
            self.text_accent = v;
        }
        if let Some(v) = refinement.element_background {
            self.element_background = v;
        }
        if let Some(v) = refinement.element_hover {
            self.element_hover = v;
        }
        if let Some(v) = refinement.element_selected {
            self.element_selected = v;
        }
    }
}
