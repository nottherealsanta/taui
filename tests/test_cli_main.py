from __future__ import annotations

import asyncio
from pathlib import Path

from taui.__main__ import _reinitialize_sqlite_cache


def test_reinitialize_sqlite_cache_recreates_db_file(tmp_path: Path) -> None:
    workspace = (tmp_path / "workspace").resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    db_path, removed = asyncio.run(_reinitialize_sqlite_cache(workspace))
    assert db_path.exists()
    assert removed is False
    first_size = db_path.stat().st_size
    assert first_size > 0

    db_path.write_text("stale-cache", encoding="utf-8")
    stale_size = db_path.stat().st_size
    assert stale_size != first_size

    db_path2, removed2 = asyncio.run(_reinitialize_sqlite_cache(workspace))
    assert db_path2 == db_path
    assert removed2 is True
    assert db_path.exists()
    assert db_path.stat().st_size > stale_size
