# System Prompt

Taui builds a system prompt from project context, tool metadata, instructions, and
extension hooks.

## Code

- Prompt builder: `taui/prompt_builder.py:123`
- Project context discovery: `taui/prompt_builder.py:98`
- Instruction file names: `taui/prompt_builder.py:36`
- Tool metadata injection: `taui/prompt_builder.py:173`
- Template rendering: `taui/prompt_builder.py:459`
- Project override file: `taui/prompt_builder.py:472`
- Session rebuild path: `taui/session.py:605`

## Inputs

Default project instructions are discovered from:

- `AGENTS.md`
- `.taui/instructions.md`
- `.taui/AGENTS.md`

Discovery walks from repo root toward the working directory, so broader instructions are
seen before more specific ones: `taui/prompt_builder.py:429`.

## Override

Create `.taui/system_prompt.md` to replace the default template. Supported placeholders
are rendered by `render_template()`: `taui/prompt_builder.py:459`.

Extensions can transform the final prompt with the `system_prompt` hook:
`taui/session.py:619`.
