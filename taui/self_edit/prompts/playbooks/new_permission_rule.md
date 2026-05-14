# Playbook: Create a Permission Rule

## Goal
Add permission rules to control tool access patterns.

## Steps

1. Ask the user what they want to allow/deny.
2. Add rules to `.taui/config.toml` or as an extension.

### Config-based rules (`.taui/config.toml`)

```toml
[taui.permission]
read = { "*" = "allow", "*.env" = "ask", ".env.example" = "allow" }
bash = { "git status" = "allow", "git push" = "ask", "*" = "ask" }
edit = { "src/**" = "allow", "*" = "ask" }
```

### Extension-based rules

```python
def register(ctx):
    ctx.hooks.policy.add_rules({
        "bash": {"git status": "allow", "git push": "ask", "*": "ask"},
        "edit": {"src/**": "allow", "*": "ask"},
    }, layer="extension")
```

### Pattern syntax

- `*` matches everything
- `*.ext` matches files by extension
- `dir/**` matches recursively in a directory
- Longest matching pattern wins
- Layers cascade: variant > project > global

3. Write the config or extension file.
4. Tell the user to run `/reload` to activate.
