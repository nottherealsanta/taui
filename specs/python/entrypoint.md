- ## Entry Point
    CLI and server bootstrap. Resolves workspace, binds an OS-assigned port, and launches Uvicorn with the FastAPI app.
    - {{status: draft}}
    - {{code_ref: `taui/__main__.py`}}

    - ### CLI (`__main__.py`)
        argparse-based CLI with two subcommands: `serve` and `reinit-db`.
        - {{status: draft}}

        - #### serve subcommand
            Resolves workspace path to absolute. Picks a free port (or uses --port if > 0). Calls create_app(), starts Uvicorn.
            Prints `Taui backend running at ws://<host>:<port>/ws` to stdout for the UI to parse.
            - {{status: draft}}

        - #### reinit-db subcommand
            Deletes the existing SQLite snapshot file for the workspace, then reinitialises an empty in-memory DB.
            Used to recover from a corrupt snapshot without losing the spec markdown files.
            - {{status: draft}}

        - #### _find_free_port()
            Binds a temporary TCP socket to 127.0.0.1:0 to get an OS-assigned free port, then closes the socket.
            - {{status: draft}}

    - ### Server entry (`server/__main__.py`)
        Alternative module entry point used when running `python -m taui.server`.
        - {{status: draft}}
        - {{code_ref: `taui/server/__main__.py`}}
