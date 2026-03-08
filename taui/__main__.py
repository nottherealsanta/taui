from __future__ import annotations

import asyncio
import argparse
import logging
from pathlib import Path
import socket
import sys

import uvicorn

from taui.logging import configure_logging
from taui.server.app import create_app
from taui.specs import SpecDB

logger = logging.getLogger(__name__)


def _find_free_port(host: str) -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


async def _reinitialize_sqlite_cache(workspace: Path) -> tuple[Path, bool]:
    db = SpecDB(workspace)
    db_path = db.db_path
    removed = db_path.exists()
    if removed:
        db_path.unlink()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    await db.connect()
    await db.close()
    return db_path, removed


def _run_serve(args: argparse.Namespace) -> None:
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


def _run_reinit_db(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    db_path, removed = asyncio.run(_reinitialize_sqlite_cache(workspace))
    action = "Reset" if removed else "Initialized"
    print(f"{action} Taui cache DB at {db_path}", flush=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="taui web UI")
    subparsers = parser.add_subparsers(dest="command")

    serve_parser = subparsers.add_parser("serve", help="Run Taui web UI server")
    serve_parser.add_argument(
        "--workspace",
        default=".",
        help="Workspace root that contains specs/",
    )
    serve_parser.add_argument(
        "--path",
        "--specs-path",
        dest="specs_path",
        default="specs",
        help="Path to the specs root directory (relative to workspace by default)",
    )
    serve_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host interface to bind",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind (0 picks a free port)",
    )
    serve_parser.set_defaults(func=_run_serve)

    reinit_parser = subparsers.add_parser(
        "reinit-db",
        help="Delete and recreate Taui's SQLite cache DB for a workspace",
    )
    reinit_parser.add_argument(
        "--workspace",
        default=".",
        help="Workspace root used to derive cache DB location",
    )
    reinit_parser.set_defaults(func=_run_reinit_db)
    return parser


def main() -> None:
    configure_logging()
    parser = _build_parser()
    argv = sys.argv[1:]
    if argv and argv[0] in {"-h", "--help"}:
        parser.parse_args(argv)
        return
    if not argv or argv[0] not in {"serve", "reinit-db"}:
        argv = ["serve", *argv]
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
