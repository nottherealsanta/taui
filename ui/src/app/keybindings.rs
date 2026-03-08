use gpui::Keystroke;

use super::actions::UiAction;

pub fn map_key_to_action(keystroke: &Keystroke) -> Option<UiAction> {
    let raw_key = keystroke.key.to_string();
    let key = raw_key.to_ascii_lowercase();

    match key.as_str() {
        "arrowdown" | "down" => Some(UiAction::SelectNext),
        "arrowup" | "up" => Some(UiAction::SelectPrevious),
        "tab" => {
            if keystroke.modifiers.shift {
                Some(UiAction::OutdentNode)
            } else {
                Some(UiAction::IndentNode)
            }
        }
        "enter" => Some(UiAction::AddSiblingNode),
        "escape" => Some(UiAction::StopEditing),
        "f2" => Some(UiAction::StartEditing),
        "backspace" => Some(UiAction::Backspace),
        " " => Some(UiAction::InsertText(" ".to_string())),
        "s" if keystroke.modifiers.control => Some(UiAction::CycleStatus),
        _ => {
            if keystroke.modifiers.control || keystroke.modifiers.alt {
                return None;
            }

            if raw_key.chars().count() == 1 {
                return Some(UiAction::InsertText(raw_key));
            }

            None
        }
    }
}
