- ## Server
    FastAPI application exposing /healthz REST and /ws WebSocket endpoints. Single-client enforced. All backend-frontend communication is JSON-RPC 2.0 over WebSocket.
    - {{status: draft}}
    - ### App (`app.py`)
        FastAPI app factory. Wires lifespan, connection manager, and handler dispatch.
        - {{status: draft}}
        - {{code_ref: `taui/server/app.py`}}
        - #### _ConnectionManager
            Enforces one-client-at-a-time with asyncio.Lock. Rejects a second WebSocket connection with close code 1013.
            - {{status: draft}}
        - #### create_app()
            Factory: creates MethodHandlers with workspace/specs_path/dev_mode. Registers lifespan and HTTP + WebSocket routes.
            - {{status: draft}}
        - #### lifespan
            Startup: calls specs.ensure_initialized() and agent_manager.startup_recovery().
            Shutdown: stops agents, flushes writer, closes DB.
            - {{status: draft}}
        - #### GET /healthz
            Liveness probe. Returns `{"status": "ok"}`.
            - {{status: draft}}
        - #### WebSocket /ws
            Main RPC channel. Registers client, read-loops JSON messages, dispatches via handlers.dispatch(), sends result then pending notifications in sequence.
            - {{status: draft}}
    - ### Handlers (`handlers.py`)
        MethodHandlers class: central router for all JSON-RPC methods. Owns SpecService, RunState, AgentManager.
        - {{status: draft}}
        - {{code_ref: `taui/server/handlers.py`}}
        - #### MethodHandlers.__init__()
            Constructs SpecService, RunState, and AgentManager. Wires notification callback so agent events reach the WebSocket.
            - {{status: draft}}
        - #### dispatch()
            Routes method string to the matching private handler. Wraps response in DispatchResult(result, notifications[]).
            Logs method, request_id, and elapsed time on every call.
            - {{status: draft}}
        - #### initialize / shutdown / exit
            Session lifecycle. initialize returns server capabilities dict. shutdown is a no-op ack. exit signals clean shutdown.
            - {{status: draft}}
        - #### spec/getTree
            Returns flat list of SpecNode dicts from SpecService.get_tree().
            - {{status: draft}}
        - #### spec/getTreeDetailed
            Returns flat list of SpecNodeDetail dicts including line_start and line_end.
            - {{status: draft}}
        - #### spec/getNode
            Returns SpecNodeDetail for a single spec_ref. Raises INVALID_PARAMS if not found.
            - {{status: draft}}
        - #### spec/getNodeSourceRange
            Returns {file_path, line_start, line_end} for a spec_ref. Used by editor jump-to-source.
            - {{status: draft}}
        - #### spec/getNodeCodeRefs
            Returns list of code_ref strings attached to a spec node.
            - {{status: draft}}
        - #### spec/updateNode
            Applies SpecNodePatch (markdown field) via SpecService.update_node(). Emits spec/nodeChanged notification.
            - {{status: draft}}
        - #### spec/createSiblingNode
            Creates a new sibling after the target node via SpecService.create_sibling_node(). Emits spec/treeChanged notification.
            - {{status: draft}}
        - #### spec/indentNode
            Makes target node a child of its previous sibling via SpecService.indent_node(). Emits spec/treeChanged notification.
            - {{status: draft}}
        - #### spec/outdentNode
            Promotes target node one level up via SpecService.outdent_node(). Emits spec/treeChanged notification.
            - {{status: draft}}
        - #### spec/setNodeCollapsed
            Updates collapsed UI state for a node in the DB. No writeback; collapsed state is in-memory/snapshot only.
            - {{status: draft}}
        - #### run/start
            Spawns an async subprocess for a verification or arbitrary command. Streams stdout/stderr as run/output notifications. Sends run/completed on exit with exit_code and duration_ms.
            - {{status: draft}}
        - #### run/stop
            Sends SIGTERM to the active subprocess. Transitions RunState to stopping.
            - {{status: draft}}
        - #### run/status
            Returns current RunState dict: status, run_id, spec_ref.
            - {{status: draft}}
        - #### agent/start
            Launches an AgentRunner via AgentManager.launch(). Params: spec_ref, task, tier, llm provider, model.
            Returns agent_id.
            - {{status: draft}}
        - #### agent/stop
            Requests graceful stop of a running agent by agent_id.
            - {{status: draft}}
        - #### agent/status
            Returns current AgentState and cumulative token usage for an agent_id.
            - {{status: draft}}
        - #### agent/subscribe / agent/unsubscribe
            Registers or removes a detailed event subscription for an agent_id. Subscribed agents forward all AgentEvents as notifications.
            - {{status: draft}}
    - ### Protocol (`protocol.py`)
        JSON-RPC 2.0 message parsing, error codes, and envelope builders.
        - {{status: draft}}
        - {{code_ref: `taui/server/protocol.py`}}
        - #### JsonRpcRequest
            Dataclass: jsonrpc (must be "2.0"), method (str), params (dict), request_id (int | str | None).
            - {{status: draft}}
        - #### parse_request()
            Validates raw dict structure. Raises JsonRpcProtocolError on missing fields or wrong types.
            - {{status: draft}}
        - #### Error codes
            PARSE_ERROR (-32700), METHOD_NOT_FOUND (-32601), INVALID_PARAMS (-32602), SPEC_SERVICE_ERROR (-32000).
            - {{status: draft}}
        - #### Message builders
            result_message(id, result) → success envelope.
            error_message(id, code, message, data) → error envelope.
            notification_message(method, params) → notification envelope (no id).
            - {{status: draft}}
    - ### State (`state.py`)
        In-process state objects for the currently active run slot.
        - {{status: draft}}
        - {{code_ref: `taui/server/state.py`}}
        - #### RunProcess
            Holds asyncio subprocess handle, command string, workdir, status ("running"|"done"|"stopped"), exit_code, output_buffer list, and start/finish timestamps.
            - {{status: draft}}
        - #### RunState
            One-slot run tracker per server instance. Fields: next_run_id counter, status, run_id, spec_ref, current_process, notification_queue.
            - {{status: draft}}
