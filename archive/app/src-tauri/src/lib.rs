use tauri::menu::{Menu, MenuItem, Submenu};
use tauri::Emitter;

pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            let handle = app.handle();

            // ── File menu ────────────────────────────────────────────────────
            let quit = MenuItem::with_id(handle, "quit", "Quit", true, Some("CmdOrCtrl+Q"))?;
            let file_menu = Submenu::with_items(handle, "File", true, &[&quit])?;

            // ── Edit menu ────────────────────────────────────────────────────
            let undo = MenuItem::with_id(handle, "undo", "Undo", true, Some("CmdOrCtrl+Z"))?;
            let redo = MenuItem::with_id(handle, "redo", "Redo", true, Some("CmdOrCtrl+Shift+Z"))?;
            let edit_menu = Submenu::with_items(handle, "Edit", true, &[&undo, &redo])?;

            // ── View menu ────────────────────────────────────────────────────
            let toggle_theme = MenuItem::with_id(handle, "toggle_theme", "Toggle Theme", true, None::<&str>)?;
            let command_palette = MenuItem::with_id(handle, "command_palette", "Command Palette", true, Some("CmdOrCtrl+Shift+P"))?;
            let quick_jump = MenuItem::with_id(handle, "quick_jump", "Quick Jump", true, Some("CmdOrCtrl+P"))?;
            let view_menu = Submenu::with_items(handle, "View", true, &[&toggle_theme, &command_palette, &quick_jump])?;

            let menu = Menu::with_items(handle, &[&file_menu, &edit_menu, &view_menu])?;
            app.set_menu(menu)?;

            // Handle menu events
            app.on_menu_event(move |app, event| {
                match event.id().as_ref() {
                    "quit" => {
                        app.exit(0);
                    }
                    "toggle_theme" => {
                        let _ = app.emit("menu://toggle_theme", ());
                    }
                    "command_palette" => {
                        let _ = app.emit("menu://command_palette", ());
                    }
                    "quick_jump" => {
                        let _ = app.emit("menu://quick_jump", ());
                    }
                    _ => {}
                }
            });

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
