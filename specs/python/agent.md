- ## Agent
    Async think→tool→observe loop. AgentManager coordinates multiple AgentRunner instances; each runner persists its session to SpecDB.
    - {{status: draft}}
    - {{code_ref: `taui/agent/`}}
    - ### AgentManager (`manager.py`)
        Central coordinator. Launches, stops, and monitors all AgentRunner instances. Forwards events as WebSocket notifications.
        - {{status: draft}}
        - {{code_ref: `taui/agent/manager.py`}}
        - #### launch()
            Creates agent_id and session_id (UUID4). Persists session to DB via create_agent_session(). Constructs AgentRunner. Calls runner.start(). Accepts: spec_ref, task, tier, llm client, model, tool_registry, optional spec_service, optional parent_agent_id.
            Returns the AgentRunner.
            - {{status: draft}}
        - #### stop(agent_id)
            Looks up runner by agent_id. Calls runner.stop(). Runner transitions to STOPPING state.
            - {{status: draft}}
        - #### get_status(agent_id)
            Returns current AgentState enum value and session summary dict for the runner.
            - {{status: draft}}
        - #### subscribe(agent_id) / unsubscribe(agent_id)
            Adds/removes agent_id from _subscriptions set. Subscribed agents have all AgentEvents forwarded as individual notifications over the WebSocket.
            - {{status: draft}}
        - #### _on_agent_event(event)
            Internal callback invoked by runners. Appends event to _event_buffers[agent_id]. If agent is in _subscriptions or event_type is "state_change", emits notification immediately via _notification_callback.
            - {{status: draft}}
        - #### startup_recovery()
            Called on server startup. Queries DB for sessions in non-terminal states (idle, running, thinking, tool_execution, stopping). Marks them "interrupted" so the UI can show stale-session warnings.
            - {{status: draft}}
        - #### shutdown()
            Calls stop() on all active runners. Waits for them to reach terminal state.
            - {{status: draft}}
    - ### AgentRunner (`runner.py`)
        Runs a single agent session. Manages the think→tool→observe loop with DB persistence.
        - {{status: draft}}
        - {{code_ref: `taui/agent/runner.py`}}
        - #### AgentState (enum)
            IDLE, RUNNING, THINKING, TOOL_EXECUTION, STOPPING, DONE.
            - {{status: draft}}
        - #### AgentEvent
            Dataclass: agent_id (str), event_type ("state_change" | "tool_call" | "tool_result" | "message" | "token"), payload (dict).
            - {{status: draft}}
        - #### start()
            Creates asyncio.Task for _run_loop(). Transitions state to RUNNING. Fires state_change event.
            - {{status: draft}}
        - #### _run_loop()
            Main coroutine. Builds system prompt. Loads prior messages from DB. Loop:
            1. Call LLM (THINKING state) → ProviderTurnResult.
            2. Save assistant message to DB.
            3. If no tool_calls → set DONE, break.
            4. For each tool call: execute (TOOL_EXECUTION state), save result.
            5. Check _stop_requested → break if set.
            Fires events at each state transition and tool boundary.
            - {{status: draft}}
        - #### _execute_tool(tool_call)
            Delegates to ToolExecutor.run(). On ExecutionRequiresApproval: emits approval/request notification and waits for UI response. On approval: re-runs with approved=True. Saves tool_call and result to DB.
            - {{status: draft}}
        - #### stop()
            Sets _stop_requested = True. Running loop checks the flag between LLM calls.
            - {{status: draft}}
        - #### _transition_state(new_state)
            Updates self._state. Fires AgentEvent(event_type="state_change"). Persists new state to DB via update_agent_state().
            - {{status: draft}}
        - #### _AgentSession helper
            Thin wrapper injected into ToolContext so spec-tree tools can reach SpecService and AgentRunner without circular imports.
            - {{status: draft}}
    - ### Session (`session.py`)
        In-memory conversation state with token budget compaction.
        - {{status: draft}}
        - {{code_ref: `taui/agent/session.py`}}
        - #### Session
            Fields: session_id (UUID hex), messages (list[Message]), usage (SessionUsage), created_at, updated_at, _read_attempts (path → status dict).
            - {{status: draft}}
        - #### add_message(message)
            Appends message to messages list. Updates updated_at timestamp.
            - {{status: draft}}
        - #### compact_for_token_budget(max_input_tokens, reserved_output_tokens, soft_ratio, hard_ratio)
            Drops oldest droppable messages until estimated tokens < soft_ratio * available.
            Preserves: system message, most recent user turn, most recent assistant turn.
            Raises ValueError if hard_limit still cannot be met.
            Returns True if any messages were dropped.
            - {{status: draft}}
        - #### estimated_input_tokens()
            Heuristic character-based token estimate across all messages. Used to trigger compaction.
            - {{status: draft}}
        - #### mark_read(path, status)
            Records file read attempt (path → status string). Prevents redundant re-reads within a session.
            - {{status: draft}}
        - #### record_usage(usage)
            Accumulates input_tokens and output_tokens into SessionUsage totals.
            - {{status: draft}}
