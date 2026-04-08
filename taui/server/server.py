from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from .app import create_app as _create_app


def create_app(
    workspace: Path | str | None = None,
    tangles_path: Path | str | None = None,
    specs_path: Path | str | None = None,
) -> FastAPI:
    return _create_app(
        workspace=workspace,
        tangles_path=tangles_path,
        specs_path=specs_path,
    )
