from __future__ import annotations

import argparse
from pathlib import Path
import socket

import uvicorn

from taui.server.app import create_app


def _find_free_port(host: str) -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="taui web UI")
    parser.add_argument(
        "--workspace",
        default=".",
        help="Workspace root that contains specs/",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host interface to bind",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Port to bind (0 picks a free port)",
    )
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    host = args.host
    port = args.port if args.port > 0 else _find_free_port(host)

    app = create_app(workspace=workspace)
    print(f"Taui running at http://{host}:{port}", flush=True)
    uvicorn.run(app, host=host, port=port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
