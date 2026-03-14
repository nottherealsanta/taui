- ## Tools
    Policy-gated tool execution framework. Tools implement the Tool protocol. ToolExecutor enforces policy decisions and async timeouts.
    - {{status: draft}}
    - ### Base types (`base.py`)
        Core interfaces for all tools and their execution context.
        - {{status: draft}}
        - {{code_ref: `taui/tools/base.py`}}
        - #### Tool (Protocol)
            Structural protocol. Required attributes: name (str), description (str), schema (JSON Schema dict), origin ("builtin" | "mcp:<server>"). Required method: async execute(arguments, context) → ToolResult.
            - {{status: draft}}
        - #### ToolResult
            fields: content (str), error (bool, default False), metadata (optional dict).
            Class methods: ok(content, metadata) and fail(content, metadata) for ergonomic construction.
            - {{status: draft}}
        - #### ToolContext
            Passed to every execute() call. Fields: working_dir (Path), session (Any — duck-typed Session/AgentSession), policy (Policy).
            - {{status: draft}}
    - ### Registry (`registry.py`)
        ToolRegistry: name-keyed map of registered Tool instances.
        - {{status: draft}}
        - {{code_ref: `taui/tools/registry.py`}}
        - #### register(tool)
            Adds tool to _tools dict. Raises ValueError on duplicate name.
            - {{status: draft}}
        - #### unregister(name)
            Removes tool by name. Raises ValueError if not found.
            - {{status: draft}}
        - #### get(name)
            Returns tool by name. Raises ValueError if not registered.
            - {{status: draft}}
        - #### list_schemas()
            Returns list of OpenAI-style function schema dicts: {"type": "function", "function": {name, description, parameters}}.
            - {{status: draft}}
        - #### names() / names_by_origin(prefix)
            names(): sorted tuple of all registered tool names.
            names_by_origin(prefix): filters by tool.origin.startswith(prefix).
            - {{status: draft}}
    - ### Executor (`executor.py`)
        ToolExecutor: evaluates policy, wraps execution with timeout, manages approval flow.
        - {{status: draft}}
        - {{code_ref: `taui/tools/executor.py`}}
        - #### run(tool_call_id, tool_name, arguments, context, approved, timeout_sec)
            1. Looks up tool from registry.
            2. Calls Policy.evaluate(tool_name) → allow/confirm/deny.
            3. deny → returns ExecutionDenied immediately.
            4. confirm (without approved=True) → returns ExecutionRequiresApproval with arguments_preview and reason.
            5. allow or approved=True → calls tool.execute() wrapped in asyncio.wait_for(timeout). Returns ExecutionCompleted.
            Logs tool name, call_id, approved flag, and elapsed time.
            - {{status: draft}}
        - #### ExecutionCompleted
            state="completed", result (ToolResult).
            - {{status: draft}}
        - #### ExecutionRequiresApproval
            state="approval_required", tool_call_id, tool_name, arguments_preview (truncated JSON), reason.
            - {{status: draft}}
        - #### ExecutionDenied
            state="denied", result (ToolResult with error=True).
            - {{status: draft}}
    - ### Builtin tools (`builtins/`)
        Built-in tool implementations. All have origin="builtin". Registered at server startup.
        - {{status: draft}}
        - {{code_ref: `taui/tools/builtins/`}}
        - #### bash (`bash.py`)
            Runs a shell command in an async subprocess. Captures combined stdout+stderr. Enforces timeout from BashPolicySettings. Validates command against allowed_commands list if configured. Returns output as content string.
            - {{status: draft}}
            - {{code_ref: `taui/tools/builtins/bash.py`}}
        - #### read (`read.py`)
            Reads a file from the workspace. Resolves path relative to working_dir. Enforces workspace boundary (rejects path traversal). Returns file content as string.
            - {{status: draft}}
            - {{code_ref: `taui/tools/builtins/read.py`}}
        - #### write (`write.py`)
            Writes content to a file in the workspace. Creates parent directories. Enforces workspace boundary. Returns success message.
            - {{status: draft}}
            - {{code_ref: `taui/tools/builtins/write.py`}}
        - #### edit (`edit.py`)
            Applies an exact string replacement in a file. Fails if old_string appears zero or more than one times (ambiguity/missing guard). Enforces workspace boundary. Returns updated line range.
            - {{status: draft}}
            - {{code_ref: `taui/tools/builtins/edit.py`}}
        - #### glob (`glob.py`)
            Lists workspace files matching a glob pattern. Returns sorted list of relative paths. Respects .gitignore if configured.
            - {{status: draft}}
            - {{code_ref: `taui/tools/builtins/glob.py`}}
        - #### grep (`grep.py`)
            Searches file content with a regex pattern. Returns matched lines with file path and 1-based line numbers. Accepts optional file pattern filter.
            - {{status: draft}}
            - {{code_ref: `taui/tools/builtins/grep.py`}}
        - #### spec_tree (`spec_tree.py`)
            Spec-tree manipulation tools accessed via SpecService. Provides: spec_get_node, spec_update_node, spec_create_sibling, spec_indent_node, spec_outdent_node. Uses ToolContext.session.spec_service for all mutations.
            - {{status: draft}}
            - {{code_ref: `taui/tools/builtins/spec_tree.py`}}
        - #### Common helpers (`_common.py`)
            Shared utilities: workspace boundary check (resolve + is_relative_to), text truncation for argument previews.
            - {{status: draft}}
            - {{code_ref: `taui/tools/builtins/_common.py`}}
