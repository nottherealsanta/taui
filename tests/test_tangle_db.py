from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from taui.tangle.db import SpecDB


def test_spec_db_persist_snapshot_false_does_not_create_cache_file(
    tmp_path: Path,
) -> None:
    """When persist_snapshot=False, SpecDB should not create a cache file."""
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "cache.db"

    async def run_test():
        db = SpecDB(workspace, db_path=db_path, persist_snapshot=False)
        await db.connect()
        # Perform some operations to ensure DB is functional
        await db.upsert_file("test.md", "hash123", 1234567890, 1234567890.0)
        await db.close()

    asyncio.run(run_test())

    # Cache file should not exist when persist_snapshot=False
    assert not db_path.exists()


def test_spec_db_persist_snapshot_true_creates_cache_file(tmp_path: Path) -> None:
    """When persist_snapshot=True (default), SpecDB should create a cache file."""
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "cache.db"

    async def run_test():
        db = SpecDB(workspace, db_path=db_path, persist_snapshot=True)
        await db.connect()
        # Perform some operations to ensure DB is functional
        await db.upsert_file("test.md", "hash123", 1234567890, 1234567890.0)
        await db.close()

    asyncio.run(run_test())

    # Cache file should exist when persist_snapshot=True
    assert db_path.exists()


def test_spec_db_default_persist_snapshot_is_true(tmp_path: Path) -> None:
    """By default, persist_snapshot should be True."""
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    db = SpecDB(workspace)
    assert db._persist_snapshot is True


def test_spec_db_operations_work_without_persistence(tmp_path: Path) -> None:
    """DB operations should work normally even when persist_snapshot=False."""
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "cache.db"

    async def run_test():
        db = SpecDB(workspace, db_path=db_path, persist_snapshot=False)
        await db.connect()

        # Insert a file
        file = await db.upsert_file("test.md", "hash123", 1234567890, 1234567890.0)
        assert file.rel_path == "test.md"

        # Retrieve the file
        retrieved = await db.get_file("test.md")
        assert retrieved is not None
        assert retrieved.rel_path == "test.md"
        assert retrieved.content_hash == "hash123"

        await db.close()

    asyncio.run(run_test())
    assert not db_path.exists()
