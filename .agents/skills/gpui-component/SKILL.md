---
name: gpui-component
description: Rich UI components (60+) for GPUI applications. Use when building desktop apps with buttons, inputs, tables, dialogs, charts, and other pre-built components.
---

# GPUI Component Library

A comprehensive UI component library with 60+ production-ready components for building desktop applications with GPUI.

## Overview

- **60+ Components**: Buttons, inputs, tables, dialogs, charts, and more
- **Stateless Design**: RenderOnce components for simplicity
- **Built-in Theming**: 20+ themes with ThemeRegistry
- **Sizes**: xsmall, small, medium, large via `Sizable` trait
- **Variants**: primary, danger, warning, success, ghost, etc.
- **High Performance**: Virtualized Table/List, 200K+ line code editor

## Installation

Add to `Cargo.toml`:

```toml
[dependencies]
gpui = "0.2"
gpui-component = "0.5"
# Optional: default icon assets
gpui-component-assets = "0.5"
```

## Setup

### 1. Initialize in main()

```rust
use gpui::*;
use gpui_component::*;

fn main() {
    let app = Application::new().with_assets(gpui_component_assets::Assets);
    
    app.run(move |cx| {
        // MUST call this first!
        gpui_component::init(cx);
        
        cx.spawn(async move |cx| {
            cx.open_window(WindowOptions::default(), |window, cx| {
                let view = cx.new(|_| MyApp);
                // Root MUST be first child of window
                cx.new(|cx| Root::new(view, window, cx))
            })?;
            Ok::<_, anyhow::Error>(())
        })
        .detach();
    });
}
```

### 2. Setup Root View for Overlays

Dialogs, sheets, and notifications need render layers:

```rust
struct MyApp {
    view: AnyView,
}

impl Render for MyApp {
    fn render(&mut self, window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        div()
            .size_full()
            .child(self.view.clone())
            .children(Root::render_dialog_layer(window, cx))
            .children(Root::render_sheet_layer(window, cx))
            .children(Root::render_notification_layer(window, cx))
    }
}
```

## Core Concepts

### Stateless Components

Most components are stateless `RenderOnce` - state is managed at view level:

```rust
Button::new("btn")
    .primary()
    .label("Click Me")
    .on_click(|_, _, _| println!("clicked"))
```

### Stateful Components

Some components manage their own state via `Entity`:

```rust
struct MyView {
    input: Entity<InputState>,
    table: Entity<TableState<MyDelegate>>,
}
```

### Sizable Trait

```rust
Button::new("btn").xsmall()  // xs
Button::new("btn").small()   // sm
Button::new("btn")            // md (default)
Button::new("btn").large()    // lg
```

### Variants

```rust
Button::new("btn").primary()
Button::new("btn").danger()
Button::new("btn").warning()
Button::new("btn").success()
Button::new("btn").ghost()
Button::new("btn").outline()
```

### Theming

```rust
use gpui_component::ActiveTheme;

div()
    .bg(cx.theme().background)
    .text_color(cx.theme().foreground)
    .border_color(cx.theme().border)
```

## Essential Components

### Button

```rust
use gpui_component::button::{Button, ButtonGroup, ButtonVariants};
use gpui_component::{Icon, IconName, Sizable};

// Basic button
Button::new("save")
    .primary()
    .label("Save")
    .on_click(|_, window, cx| {
        println!("Saved!");
    })

// With icon
Button::new("search")
    .icon(IconName::Search)
    .label("Search")

// Icon only button
Button::new("close")
    .icon(IconName::X)
    .ghost()

// States
Button::new("btn").loading(true)
Button::new("btn").disabled(true)
Button::new("btn").selected(true)

// Sizes
Button::new("btn").xsmall().label("XS")
Button::new("btn").small().label("Small")
Button::new("btn").large().label("Large")

// Compact mode
Button::new("btn").compact().label("Compact")

// With tooltip
Button::new("btn")
    .label("Help")
    .tooltip("Click for help")

// Button group
ButtonGroup::new("group")
    .child(Button::new("btn1").label("One"))
    .child(Button::new("btn2").label("Two"))
    .child(Button::new("btn3").label("Three"))

// Toggle button group
ButtonGroup::new("toggle")
    .multiple(true)
    .child(Button::new("opt1").label("A").selected(true))
    .child(Button::new("opt2").label("B"))
    .on_click(|selected, _, _| {
        println!("Selected: {:?}", selected);
    })
```

### Input & InputState

```rust
use gpui_component::input::{Input, InputState, InputEvent};

// Create view with input state
struct FormView {
    email: Entity<InputState>,
    password: Entity<InputState>,
}

impl FormView {
    fn new(window: &Window, cx: &mut Context<Self>) -> Self {
        let email = cx.new(|cx| {
            InputState::new(window, cx)
                .placeholder("Enter email...")
                .default_value("user@example.com")
        });
        
        let password = cx.new(|cx| {
            InputState::new(window, cx)
                .placeholder("Password")
                .masked(true)
        });
        
        // Subscribe to input events
        cx.subscribe_in(&email, window, |this, state, event, window, cx| {
            match event {
                InputEvent::Change => {
                    let value = state.read(cx).value();
                    println!("Email changed: {}", value);
                }
                InputEvent::PressEnter { .. } => {
                    this.submit(window, cx);
                }
                InputEvent::Focus => println!("Focused"),
                InputEvent::Blur => println!("Blurred"),
                _ => {}
            }
        }).detach();
        
        Self { email, password }
    }
    
    fn submit(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let email = self.email.read(cx).value();
        let password = self.password.read(cx).value();
        println!("Submit: {} / {}", email, password);
    }
}

impl Render for FormView {
    fn render(&mut self, _window: &mut Window, _cx: &mut Context<Self>) -> impl IntoElement {
        v_flex()
            .gap_3()
            .p_4()
            .child(
                Input::new(&self.email)
                    .prefix(Icon::new(IconName::Mail).small())
                    .cleanable(true)
            )
            .child(
                Input::new(&self.password)
                    .prefix(Icon::new(IconName::Lock).small())
                    .mask_toggle()
            )
            .child(
                Button::new("submit")
                    .primary()
                    .label("Login")
                    .on_click(|_, window, cx| {
                        // Handle login
                    })
            )
    }
}

// Validation
let input = cx.new(|cx| {
    InputState::new(window, cx)
        .validate(|text, _| text.parse::<f32>().is_ok())
});

// Pattern validation
let input = cx.new(|cx| {
    InputState::new(window, cx)
        .pattern(regex::Regex::new(r"^[a-zA-Z0-9]*$").unwrap())
});

// Mask pattern for phone
let input = cx.new(|cx| {
    InputState::new(window, cx)
        .mask_pattern("(999)-999-9999")
});

// Clean on escape
let input = cx.new(|cx| {
    InputState::new(window, cx)
        .clean_on_escape()
});
```

### Dialog

```rust
use gpui_component::dialog::DialogButtonProps;
use gpui_component::WindowExt;

// Basic dialog
window.open_dialog(cx, |dialog, _, _| {
    dialog
        .title("Welcome")
        .child("This is a dialog.")
});

// Confirm dialog
Button::new("delete")
    .danger()
    .label("Delete")
    .on_click(|_, window, cx| {
        window.open_dialog(cx, |dialog, _, _| {
            dialog
                .confirm()
                .child("Are you sure you want to delete?")
                .on_ok(|_, window, cx| {
                    // Perform delete
                    window.push_notification("Deleted!", cx);
                    true // return true to close dialog
                })
                .on_cancel(|_, window, cx| {
                    window.push_notification("Cancelled", cx);
                    true
                })
        });
    })

// Alert dialog
window.open_dialog(cx, |dialog, _, _| {
    dialog
        .alert()
        .child("Operation completed!")
});

// Form dialog
let input = cx.new(|cx| InputState::new(window, cx));
window.open_dialog(cx, move |dialog, _, _| {
    dialog
        .title("Enter Name")
        .child(Input::new(&input).placeholder("Name..."))
        .footer(|_, _, _, _| {
            vec![
                Button::new("cancel")
                    .label("Cancel")
                    .on_click(|_, window, cx| window.close_dialog(cx)),
                Button::new("ok")
                    .primary()
                    .label("OK")
                    .on_click(|_, window, cx| window.close_dialog(cx)),
            ]
        })
});

// Custom button labels
window.open_dialog(cx, |dialog, _, _| {
    dialog
        .confirm()
        .child("Restart now?")
        .button_props(
            DialogButtonProps::default()
                .cancel_text("Later")
                .ok_text("Restart Now")
                .ok_variant(ButtonVariant::Danger)
        )
        .on_ok(|_, window, cx| {
            // Restart
            true
        })
});

// Close dialog programmatically
window.close_dialog(cx);
```

### Notification

```rust
use gpui_component::notification::Notification;

// Simple notification
window.push_notification("Saved successfully", cx);

// With position
window.push_notification_at(
    Notification::new("Message")
        .position(NotificationPosition::TopRight),
    cx
);

// Custom notification
window.push_notification_at(
    Notification::new("Custom")
        .icon(IconName::Check)
        .title("Success")
        .child("Your changes have been saved.")
        .duration(Duration::from_secs(5)),
    cx
);
```

### Table

```rust
use std::ops::Range;
use gpui_component::table::{Table, TableState, TableDelegate, Column, ColumnSort, ColumnFixed};

// Define data
struct User {
    id: u64,
    name: String,
    email: String,
    role: String,
    status: String,
}

// Define delegate
struct UserTableDelegate {
    users: Vec<User>,
    columns: Vec<Column>,
}

impl UserTableDelegate {
    fn new() -> Self {
        Self {
            users: vec![
                User { id: 1, name: "Alice".into(), email: "alice@example.com".into(), role: "Admin".into(), status: "Active".into() },
                User { id: 2, name: "Bob".into(), email: "bob@example.com".into(), role: "User".into(), status: "Inactive".into() },
            ],
            columns: vec![
                Column::new("id", "ID").width(60.),
                Column::new("name", "Name").width(150.).sortable().fixed(ColumnFixed::Left),
                Column::new("email", "Email").width(200.).sortable(),
                Column::new("role", "Role").width(100.).sortable(),
                Column::new("status", "Status").width(100.),
            ],
        }
    }
}

impl TableDelegate for UserTableDelegate {
    fn columns_count(&self, _: &App) -> usize {
        self.columns.len()
    }
    
    fn rows_count(&self, _: &App) -> usize {
        self.users.len()
    }
    
    fn column(&self, col_ix: usize, _: &App) -> &Column {
        &self.columns[col_ix]
    }
    
    fn render_td(&mut self, row_ix: usize, col_ix: usize, _: &mut Window, cx: &mut Context<TableState<Self>>) -> impl IntoElement {
        let user = &self.users[row_ix];
        let col = &self.columns[col_ix];
        
        match col.key.as_ref() {
            "id" => user.id.to_string(),
            "name" => user.name.clone(),
            "email" => user.email.clone(),
            "role" => user.role.clone(),
            "status" => {
                let color = if user.status == "Active" {
                    cx.theme().success
                } else {
                    cx.theme().muted_foreground
                };
                div()
                    .text_color(color)
                    .child(user.status.clone())
            }
            _ => "".to_string(),
        }
    }
    
    fn perform_sort(&mut self, col_ix: usize, sort: ColumnSort, _: &mut Window, _: &mut Context<TableState<Self>>) {
        let key = self.columns[col_ix].key.as_ref();
        match key {
            "name" => match sort {
                ColumnSort::Ascending => self.users.sort_by(|a, b| a.name.cmp(&b.name)),
                ColumnSort::Descending => self.users.sort_by(|a, b| b.name.cmp(&a.name)),
                ColumnSort::Default => self.users.sort_by(|a, b| a.id.cmp(&b.id)),
            },
            _ => {}
        }
    }
}

// Use in view
struct UsersView {
    table: Entity<TableState<UserTableDelegate>>,
}

impl UsersView {
    fn new(window: &Window, cx: &mut Context<Self>) -> Self {
        let delegate = UserTableDelegate::new();
        let table = cx.new(|cx| {
            TableState::new(delegate, window, cx)
                .col_resizable(true)
                .col_movable(true)
                .sortable(true)
                .row_selectable(true)
        });
        Self { table }
    }
}

impl Render for UsersView {
    fn render(&mut self, _window: &mut Window, _cx: &mut Context<Self>) -> impl IntoElement {
        Table::new(&self.table)
            .stripe(true)
            .bordered(true)
    }
}

// Infinite loading
impl TableDelegate for MyDelegate {
    fn is_eof(&self, _: &App) -> bool {
        !self.has_more
    }
    
    fn load_more_threshold(&self) -> usize {
        50
    }
    
    fn load_more(&mut self, _: &mut Window, cx: &mut Context<TableState<Self>>) {
        if self.loading { return; }
        self.loading = true;
        
        cx.spawn(async move |view, cx| {
            let new_data = fetch_data().await;
            cx.update(|cx| {
                view.update(cx, |view, _| {
                    let delegate = view.table.delegate_mut();
                    delegate.users.extend(new_data);
                    delegate.loading = false;
                    delegate.has_more = false;
                });
            })
        }).detach();
    }
}
```

### Select

```rust
use gpui_component::select::Select;

// Simple select
let items = vec!["Option 1", "Option 2", "Option 3"];
let select = cx.new(|cx| {
    Select::new(items)
        .placeholder("Choose...")
        .on_select(|item, _| {
            println!("Selected: {}", item);
        })
});

// In render
div().child(select.clone())
```

### Icon

```rust
use gpui_component::{Icon, IconName};

// Basic icon
Icon::new(IconName::Search)

// With size
Icon::new(IconName::Check).small()
Icon::new(IconName::Check).large()

// With color
Icon::new(IconName::Alert).text_color(cx.theme().danger)

// In button
Button::new("btn").icon(IconName::Save).label("Save")
```

### Checkbox, Radio, Switch

```rust
use gpui_component::checkbox::Checkbox;
use gpui_component::radio::Radio;
use gpui_component::switch::Switch;

// Checkbox
Checkbox::new("agree")
    .label("I agree to terms")
    .on_click(|checked, _, _| {
        println!("Checked: {}", checked);
    })

// Radio group
Radio::new("choice")
    .options(["Option A", "Option B", "Option C"])
    .on_select(|value, _, _| {
        println!("Selected: {}", value);
    })

// Switch
Switch::new("enabled")
    .label("Enable feature")
    .on_click(|enabled, _, _| {
        println!("Enabled: {}", enabled);
    })
```

### Progress, Spinner, Skeleton

```rust
use gpui_component::progress::Progress;
use gpui_component::spinner::Spinner;
use gpui_component::skeleton::Skeleton;

// Progress bar
Progress::new().value(0.7) // 70%

// Spinner (loading indicator)
Spinner::new()
Spinner::new().small()
Spinner::new().color(cx.theme().primary)

// Skeleton (loading placeholder)
Skeleton::new().w(px(200.)).h(px(20.))
```

### Tooltip

```rust
use gpui_component::tooltip::Tooltip;

Button::new("help")
    .label("Help")
    .tooltip(|window, cx| {
        Tooltip::new("Click for help")
            .build(window, cx)
    })
```

### Tabs

```rust
use gpui_component::tab::Tabs;

let tabs = cx.new(|cx| {
    Tabs::new()
        .tab("Tab 1", "content1")
        .tab("Tab 2", "content2")
        .on_change(|index, _, _| {
            println!("Tab changed to: {}", index);
        })
});

div().child(tabs.clone())
```

### Popover

```rust
use gpui_component::popover::Popover;

Button::new("menu")
    .label("Options")
    .popover(|_, _| {
        Popover::new()
            .child(
                v_flex()
                    .child("Option 1")
                    .child("Option 2")
            )
    })
```

### Dock Layout

```rust
use gpui_component::dock::{Dock, DockItem, Panel};

// Create dock with panels
let dock = cx.new(|cx| {
    Dock::new(window, cx)
        .item(DockItem::panel(
            Panel::new("panel1", "Panel 1", cx.new(|_| MyPanel))
        ))
        .item(DockItem::panel(
            Panel::new("panel2", "Panel 2", cx.new(|_| AnotherPanel))
        ))
});

div().size_full().child(dock.clone())
```

## Best Practices

1. **Always use Root**: Root must be the first child of your window
2. **Call init()**: Always call `gpui_component::init(cx)` at app startup
3. **Hold Entity**: Store `Entity<InputState>` etc in your view struct
4. **Overlay layers**: Add `Root::render_*_layer()` in root view render
5. **Use Sizable**: Prefer `.small()` over `.with_size(Size::Small)`
6. **Theme colors**: Use `cx.theme()` for consistent styling

## Common Mistakes

| Mistake | Problem | Solution |
|---------|---------|----------|
| Missing Root wrapper | Components don't work | Wrap window content in `Root::new()` |
| Forgetting init() | Runtime errors | Call `gpui_component::init(cx)` first |
| No overlay layers | Dialogs/sheets invisible | Add `Root::render_*_layer()` in render |
| Not holding Entity | State gets dropped | Store `Entity<InputState>` in view struct |
| Missing assets | Icons don't render | Add `gpui-component-assets` dependency |

## Component Reference

### Basic Components
| Component | Description | Import |
|-----------|-------------|--------|
| Button | Interactive button | `gpui_component::button::Button` |
| Icon | SVG icon display | `gpui_component::Icon` |
| Badge | Count badge | `gpui_component::badge::Badge` |
| Tag | Label/category tag | `gpui_component::tag::Tag` |
| Spinner | Loading indicator | `gpui_component::spinner::Spinner` |
| Skeleton | Loading placeholder | `gpui_component::skeleton::Skeleton` |
| Avatar | User avatar | `gpui_component::avatar::Avatar` |
| Kbd | Keyboard shortcut | `gpui_component::kbd::Kbd` |
| Label | Form label | `gpui_component::label::Label` |
| Progress | Progress bar | `gpui_component::progress::Progress` |
| Divider | Horizontal/vertical divider | `gpui_component::divider::Divider` |

### Form Components
| Component | Description | Import |
|-----------|-------------|--------|
| Input | Text input | `gpui_component::input::{Input, InputState}` |
| Select | Dropdown select | `gpui_component::select::Select` |
| Checkbox | Checkbox control | `gpui_component::checkbox::Checkbox` |
| Radio | Radio button | `gpui_component::radio::Radio` |
| Switch | Toggle switch | `gpui_component::switch::Switch` |
| Slider | Range slider | `gpui_component::slider::Slider` |
| DatePicker | Date picker | `gpui_component::date_picker::DatePicker` |
| ColorPicker | Color picker | `gpui_component::color_picker::ColorPicker` |
| NumberInput | Numeric input | `gpui_component::input::NumberInput` |
| OtpInput | OTP input | `gpui_component::input::OtpInput` |

### Layout Components
| Component | Description | Import |
|-----------|-------------|--------|
| Dialog | Modal dialog | `gpui_component::dialog` |
| Popover | Floating content | `gpui_component::popover::Popover` |
| Sheet | Slide-in panel | `gpui_component::sheet::Sheet` |
| Sidebar | Navigation sidebar | `gpui_component::sidebar::Sidebar` |
| Tabs | Tabbed interface | `gpui_component::tab::Tabs` |
| Dock | Dockable panels | `gpui_component::dock::Dock` |
| Resizable | Resizable panels | `gpui_component::resizable::Resizable` |
| Scrollable | Scroll container | `gpui_component::scroll::Scrollable` |
| GroupBox | Grouped content | `gpui_component::group_box::GroupBox` |
| Collapse | Collapsible content | `gpui_component::collapsible::Collapse` |

### Data Components
| Component | Description | Import |
|-----------|-------------|--------|
| Table | High-performance table | `gpui_component::table::{Table, TableState, TableDelegate}` |
| List | List view | `gpui_component::list::List` |
| Tree | Tree view | `gpui_component::tree::Tree` |
| VirtualList | Virtualized list | `gpui_component::VirtualList` |
| DescriptionList | Key-value list | `gpui_component::description_list::DescriptionList` |

### Feedback Components
| Component | Description | Import |
|-----------|-------------|--------|
| Alert | Alert message | `gpui_component::alert::Alert` |
| Notification | Toast notification | `gpui_component::notification::Notification` |
| Tooltip | Hover tooltip | `gpui_component::tooltip::Tooltip` |

### Advanced Components
| Component | Description | Import |
|-----------|-------------|--------|
| Chart | Data charts | `gpui_component::chart::Chart` |
| Plot | Plotting | `gpui_component::plot::Plot` |
| Menu | Context/dropdown menu | `gpui_component::menu::PopupMenu` |
| Calendar | Calendar | `gpui_component::calendar::Calendar` |
| WebView | Embedded browser | `gpui_component::webview::WebView` |

## References

- [gpui-component docs.rs](https://docs.rs/gpui-component)
- [gpui-component GitHub](https://github.com/longbridge/gpui-component)
- [GPUI Documentation](https://gpui.rs)
