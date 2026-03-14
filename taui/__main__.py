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
    dev_mode = getattr(args, "dev", False)

    logger.info(
        "Starting Taui backend server workspace=%s host=%s port=%s dev_mode=%s",
        workspace,
        host,
        port,
        dev_mode,
    )
    app = create_app(workspace=workspace, dev_mode=dev_mode)
    print(f"Taui backend running at ws://{host}:{port}/ws", flush=True)
    uvicorn.run(app, host=host, port=port, log_level="warning", access_log=False)


def _run_reinit_db(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    db_path, removed = asyncio.run(_reinitialize_sqlite_cache(workspace))
    action = "Reset" if removed else "Initialized"
    print(f"{action} Taui cache DB at {db_path}", flush=True)


def _run_login(args: argparse.Namespace) -> None:
    from taui.auth.copilot import login

    enterprise_domain = getattr(args, "enterprise_domain", None) or None
    login(enterprise_domain=enterprise_domain)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="taui backend server")
    subparsers = parser.add_subparsers(dest="command")

    serve_parser = subparsers.add_parser("serve", help="Run Taui backend server")
    serve_parser.add_argument(
        "--workspace",
        "--path",
        dest="workspace",
        default=".",
        help="Workspace root that contains specs/",
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
    serve_parser.add_argument(
        "--dev",
        action="store_true",
        help="Disable SQLite cache read/write; rebuild DB from markdown files each run",
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

    login_parser = subparsers.add_parser(
        "login",
        help="Authenticate with GitHub Copilot via device flow",
    )
    login_parser.add_argument(
        "--enterprise-domain",
        dest="enterprise_domain",
        default="",
        help="GitHub Enterprise Server domain (e.g. github.example.com); omit for github.com",
    )
    login_parser.set_defaults(func=_run_login)

    return parser


def main() -> None:
    configure_logging()
    parser = _build_parser()
    argv = sys.argv[1:]
    if argv and argv[0] in {"-h", "--help"}:
        parser.parse_args(argv)
        return
    if not argv or argv[0] not in {"serve", "reinit-db", "login"}:
        argv = ["serve", *argv]
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
