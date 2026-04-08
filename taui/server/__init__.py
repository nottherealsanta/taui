from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

__all__ = ["create_app"]


def create_app(
    workspace: Path | str | None = None,
    tangles_path: Path | str | None = None,
    specs_path: Path | str | None = None,
) -> "FastAPI":
    from .app import create_app as _create_app

    return _create_app(
        workspace=workspace,
        tangles_path=tangles_path,
        specs_path=specs_path,
    )
