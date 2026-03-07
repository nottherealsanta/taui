from __future__ import annotations

import argparse
import logging
from pathlib import Path
import socket

import uvicorn

from taui.logging import configure_logging
from taui.server.app import create_app

logger = logging.getLogger(__name__)


def _find_free_port(host: str) -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="taui web UI")
    parser.add_argument(
        "--workspace",
        default=".",
        help="Workspace root that contains specs/",
    )
    parser.add_argument(
        "--path",
        "--specs-path",
        dest="specs_path",
        default="specs",
        help="Path to the specs root directory (relative to workspace by default)",
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

    logger.info(
        "Starting Taui UI server workspace=%s specs_path=%s host=%s port=%s",
        workspace,
        args.specs_path,
        host,
        port,
    )
    app = create_app(workspace=workspace, specs_path=args.specs_path)
    print(f"Taui running at http://{host}:{port}", flush=True)
    uvicorn.run(app, host=host, port=port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
