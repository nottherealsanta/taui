# Theme System
{{status: done}}

The theme system provides a comprehensive design token architecture for the Taui UI, including colors, typography, and semantic status colors.

## Theme Architecture
{{status: done}}

### Module Structure

```mermaid
graph TB
    subgraph ThemeModule["theme/ module"]
        MOD[mod.rs]
        COL[colors.rs]
        STA[status_colors.rs]
        SYN[syntax.rs]
        REG[registry.rs]
    end
    
    MOD --> COL
    MOD --> STA
    MOD --> SYN
    MOD --> REG
    
    COL --> TC[ThemeColors]
    STA --> SC[StatusColors]
    SYN --> ST[SyntaxTheme]
    REG --> TR[ThemeRegistry]
```

### Theme Hierarchy

```mermaid
classDiagram
    class ThemeColors {
        +u32 background
        +u32 panel_background
        +u32 elevated_surface_background
        +u32 border
        +u32 border_variant
        +u32 text
        +u32 text_muted
        +u32 text_accent
        +u32 element_background
        +u32 element_hover
        +u32 element_selected
    }
    
    class StatusColors {
        +u32 error
        +u32 warning
        +u32 info
        +u32 success
        +u32 spec_draft
        +u32 spec_ready
        +u32 spec_in_progress
        +u32 spec_done
        +u32 spec_blocked
        +u32 box_completed
        +u32 box_failed
        +u32 box_partial
        +u32 box_halted
        +u32 clarification_blocking
        +u32 clarification_non_blocking
        +u32 amendment_proposed
        +u32 amendment_accepted
        +u32 amendment_rejected
        +u32 verification_met
        +u32 verification_unmet
        +u32 verification_ambiguous
    }
    
    class SyntaxTheme {
        +Vec~(String,HighlightStyle)~ highlights
    }
    
    class HighlightStyle {
        +Option~u32~ color
        +Option~u32~ background_color
        +Option~bool~ italic
        +Option~bool~ bold
    }
    
    class ThemeStyles {
        +ThemeColors colors
        +StatusColors status
        +SyntaxTheme syntax
    }
    
    class Theme {
        +String name
        +Appearance appearance
        +ThemeStyles styles
    }
    
    class ThemeFamily {
        +String name
        +String author
        +Vec~Theme~ themes
    }
    
    class ThemeRegistry {
        +Vec~ThemeFamily~ families
    }
    
    ThemeStyles --> ThemeColors
    ThemeStyles --> StatusColors
    ThemeStyles --> SyntaxTheme
    SyntaxTheme --> HighlightStyle
    Theme --> ThemeStyles
    ThemeFamily --> Theme
    ThemeRegistry --> ThemeFamily
```

## Color System
{{status: done}}

### UI Color Tokens

```mermaid
mindmap
  root((ThemeColors))
    Surfaces
      background
      panel_background
      elevated_surface_background
    Borders
      border
      border_variant
    Text
      text
      text_muted
      text_accent
    Elements
      element_background
      element_hover
      element_selected
```

### Taui Dark Palette

| Token | Value | Description |
|-------|-------|-------------|
| background | `#0d1117` | Main background |
| panel_background | `#161b22` | Panel surfaces |
| border | `#30363d` | Primary borders |
| text | `#e6edf3` | Primary text |
| text_muted | `#7d8590` | Secondary text |
| element_selected | `#1f6feb` | Selection highlight |

### Taui Light Palette

| Token | Value | Description |
|-------|-------|-------------|
| background | `#ffffff` | Main background |
| panel_background | `#f6f8fa` | Panel surfaces |
| border | `#d0d7de` | Primary borders |
| text | `#1f2328` | Primary text |
| text_muted | `#656d76` | Secondary text |
| element_selected | `#0969da` | Selection highlight |

## Status Colors
{{status: done}}

### Semantic Color Categories

```mermaid
graph TB
    subgraph General["General"]
        E[error]
        W[warning]
        I[info]
        S[success]
    end
    
    subgraph SpecStatus["Spec Node Status"]
        SD[spec_draft]
        SR[spec_ready]
        SI[spec_in_progress]
        SN[spec_done]
        SB[spec_blocked]
    end
    
    subgraph BoxStatus["Execution Box Status"]
        BC[box_completed]
        BF[box_failed]
        BP[box_partial]
        BH[box_halted]
    end
    
    subgraph Clarification["Clarification Events"]
        CB[clarification_blocking]
        CN[clarification_non_blocking]
    end
    
    subgraph Amendment["Amendment Events"]
        AP[amendment_proposed]
        AA[amendment_accepted]
        AR[amendment_rejected]
    end
    
    subgraph Verification["Verification Outcomes"]
        VM[verification_met]
        VU[verification_unmet]
        VA[verification_ambiguous]
    end
```

### Status Color Mapping

```mermaid
flowchart LR
    subgraph StatusToColor["Status → Color"]
        D[draft] --> C1[spec_draft]
        R[ready] --> C2[spec_ready]
        IP[in-progress] --> C3[spec_in_progress]
        DN[done] --> C4[spec_done]
        BL[blocked] --> C5[spec_blocked]
        UK[Unknown] --> C6[text_muted]
    end
```

## Typography
{{status: done}}

### Heading Styles

```mermaid
flowchart TD
    subgraph DepthStyles["Depth → Style"]
        D0["Depth 0"] --> S0["32px SEMIBOLD"]
        D1["Depth 1"] --> S1["28px SEMIBOLD"]
        D2["Depth 2"] --> S2["24px SEMIBOLD"]
        D3["Depth 3"] --> S3["21px MEDIUM"]
        D4["Depth 4"] --> S4["18px MEDIUM"]
        D5["Depth 5+"] --> S5["16px NORMAL"]
    end
```

### Font Weights

| Constant | Value | Usage |
|----------|-------|-------|
| NORMAL | 400 | Body text |
| MEDIUM | 500 | Level 3-4 headings |
| SEMIBOLD | 600 | Level 0-2 headings |

### Content Style

```mermaid
classDiagram
    class ContentStyle {
        +Pixels font_size: 14px
        +FontWeight font_weight: NORMAL
        +f32 line_height: 1.5
        +Font font: monospace
    }
```

### Layout Constants

| Constant | Value | Purpose |
|----------|-------|---------|
| MAX_CONTENT_WIDTH | 960px | Document column width |
| INDENT_PER_LEVEL | 24px | Tree indent increment |

## Theme Registry
{{status: done}}

### Built-in Theme Families

```mermaid
graph TB
    subgraph TauiFamily["Taui Family"]
        TD[Taui Dark]
        TL[Taui Light]
    end
    
    subgraph ZedFamily["Zed One Family"]
        ZD[Zed One Dark]
    end
    
    TR[ThemeRegistry] --> TauiFamily
    TR --> ZedFamily
```

### Theme Loading

```mermaid
sequenceDiagram
    participant App as AppShell
    participant Reg as ThemeRegistry
    participant Fam as ThemeFamily
    
    App->>Reg: load_bundled_themes()
    Reg->>Fam: Create Taui family
    Reg->>Fam: Create Zed One family
    Reg-->>App: Vec~ThemeFamily~
    
    App->>Reg: default_light()
    Reg->>Reg: Find "light" in name
    Reg-->>App: Theme
```

### Default Theme Selection

```mermaid
flowchart TD
    A[default_light] --> B{Theme name has "light"?}
    B -->|Yes| C[Return that theme]
    B -->|No| D[Find Appearance::Light]
    D --> E[Return first match]
    
    F[default_dark] --> G{Theme name has "dark"?}
    G -->|Yes| H[Return that theme]
    G -->|No| I[Find Appearance::Dark]
    I --> J[Return first match]
```

## Theme Refinement
{{status: done}}

### Refinement Pattern

```mermaid
classDiagram
    class ThemeColorsRefinement {
        +Option~u32~ background
        +Option~u32~ panel_background
        +Option~u32~ border
        ...all fields optional
    }
    
    class ThemeColors {
        +refine(ThemeColorsRefinement) ThemeColors
    }
    
    ThemeColors --> ThemeColorsRefinement : applies
```

### Refinement Flow

```mermaid
flowchart LR
    A[Base ThemeColors] --> B[ThemeColorsRefinement]
    B --> C[Override specified fields]
    C --> D[New ThemeColors]
```

## Usage in Components
{{status: done}}

### Current Implementation Gap

```mermaid
flowchart TD
    A[Theme loaded] --> B[Stored in AppShell.theme]
    B --> C{Used in render?}
    C -->|Currently| D[Hardcoded rgb values]
    C -->|Future| E[self.theme.styles.colors.*]
    
    Note1[Note: Theme system defined but not wired]
```

### Intended Usage

```mermaid
flowchart TD
    A[render method] --> B[self.theme.styles.colors]
    B --> C[background]
    B --> D[text]
    B --> E[border]
    
    F[Status rendering] --> G[self.theme.styles.status]
    G --> H[spec_draft]
    G --> I[spec_done]
    G --> J[spec_blocked]
```

## Future Enhancements
{{status: done}}

### Planned Features

```mermaid
mindmap
  root((Future))
    User Themes
      JSON loading
      Custom palettes
    Dynamic Switching
      Light/dark toggle
      Per-workspace themes
    Syntax Highlighting
      Code block colors
      Language-specific
    Animations
      Transition effects
      Hover states
```

### User Theme Loading (Stub)

```mermaid
sequenceDiagram
    participant App
    participant Reg as ThemeRegistry
    participant FS as File System
    
    App->>Reg: load_user_themes(path)
    Reg->>FS: Check path exists
    alt Exists
        Reg->>FS: Read JSON files
        FS-->>Reg: Theme definitions
        Reg->>Reg: Parse and validate
        Reg-->>App: Vec~Theme~
    else Not exists
        Reg-->>App: Empty Vec
    end
```
