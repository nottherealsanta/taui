from __future__ import annotations

import argparse
import logging
from pathlib import Path
import socket
import sys

from taui.log_config import configure_logging

logger = logging.getLogger(__name__)


def _bind_free_socket() -> socket.socket:
    """Bind to an OS-assigned free port on localhost and return the open socket.

    The caller is responsible for closing the socket when done.  We keep it
    open so that the port cannot be claimed by another process between the
    time we discover it and the time Uvicorn calls ``loop.create_server``.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    return sock


def _serve(
    workspace: Path,
    tangles_path: Path | str | None = None,
    specs_path: Path | str | None = None,
) -> int:
    try:
        from .app import create_app
        import uvicorn
    except ModuleNotFoundError as exc:
        print(f"Missing dependency: {exc.name}", file=sys.stderr)
        return 1

    # Bind once to claim a free port, keep socket open so no other process
    # can steal it before Uvicorn takes over.
    bound_sock = _bind_free_socket()
    port = bound_sock.getsockname()[1]

    app = create_app(
        workspace=workspace,
        tangles_path=tangles_path,
        specs_path=specs_path,
    )
    logger.info(
        "Starting Taui IPC server workspace=%s tangles_path=%s specs_path=%s",
        workspace,
        tangles_path,
        specs_path,
    )

    # Subclass Server so we can print PORT: only after startup() has finished
    # (i.e. the socket is already in the accept() backlog and ready for
    # connections).  Printing before startup() completes causes a race where
    # the test client connects before the kernel starts accepting.
    class _TauiServer(uvicorn.Server):
        async def startup(self, sockets=None):  # type: ignore[override]
            await super().startup(sockets=sockets)
            if self.started:
                logger.info("Taui IPC server started on 127.0.0.1:%s", port)
                print(f"PORT:{port}", flush=True)

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = _TauiServer(config)
    server.run(sockets=[bound_sock])
    bound_sock.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description="Taui FastAPI server")
    subparsers = parser.add_subparsers(dest="command")

    serve_parser = subparsers.add_parser("serve", help="Run the IPC server")
    serve_parser.add_argument(
        "--workspace",
        default=".",
        help="Workspace root that contains tangles/",
    )
    serve_parser.add_argument(
        "--tangles-path",
        dest="tangles_path",
        default="tangles",
        help="Path to the tangles root directory (relative to workspace by default)",
    )
    serve_parser.add_argument(
        "--path",
        "--specs-path",
        dest="specs_path",
        default=None,
        help="Path to the specs root directory (relative to workspace by default)",
    )

    args = parser.parse_args(argv)
    if args.command == "serve":
        workspace = Path(args.workspace).resolve()
        return _serve(
            workspace,
            tangles_path=args.tangles_path,
            specs_path=args.specs_path,
        )

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
