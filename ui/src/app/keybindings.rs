use gpui::Keystroke;

use super::actions::UiAction;

pub fn map_key_to_action(keystroke: &Keystroke) -> Option<UiAction> {
    let raw_key = keystroke.key.to_string();
    let key = raw_key.to_ascii_lowercase();

    match key.as_str() {
        "arrowdown" | "down" => Some(UiAction::SelectNext),
        "arrowup" | "up" => Some(UiAction::SelectPrevious),
        "arrowleft" | "left" => None,
        "arrowright" | "right" => None,
        "home" => None,
        "end" => None,
        "tab" => {
            if keystroke.modifiers.shift {
                Some(UiAction::OutdentNode)
            } else {
                Some(UiAction::IndentNode)
            }
        }
        "enter" => None, // handled directly in handle_key_down before input focus check
        "escape" => None,
        "f2" => None,
        "backspace" => None,
        "delete" => None,
        " " => None,
        _ => None,
    }
}
