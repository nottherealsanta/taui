"""File-state tracker — detects external modifications between Read and Edit/Write."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class FileSnapshot:
    """Recorded state of a file at time of read."""

    mtime_ns: int
    content_hash: str  # sha256 hex digest
    size: int


class FileTracker:
    """Tracks file state across tool calls within a session.

    When a file is read, its mtime and content hash are recorded.
    Before a write/edit, the tracker checks if the file changed externally.
    """

    def __init__(self) -> None:
        self._snapshots: dict[Path, FileSnapshot] = {}

    def record_read(self, path: Path) -> None:
        """Record the state of a file after reading it."""
        resolved = path.resolve()
        if not resolved.is_file():
            return
        stat = resolved.stat()
        content_hash = hashlib.sha256(resolved.read_bytes()).hexdigest()
        self._snapshots[resolved] = FileSnapshot(
            mtime_ns=stat.st_mtime_ns,
            content_hash=content_hash,
            size=stat.st_size,
        )

    def check_before_write(self, path: Path) -> str | None:
        """Check if a file was modified externally since last read.

        Returns None if OK to write, or an error message string if the file
        changed and should be re-read first.
        """
        resolved = path.resolve()
        snapshot = self._snapshots.get(resolved)
        if snapshot is None:
            # Never read — allow write (could be a new file)
            if not resolved.exists():
                return None
            # File exists but was never read — require read first
            return (
                f"File {path} exists but has not been read in this session. "
                f"Read the file first to establish a baseline, then retry the edit."
            )

        if not resolved.is_file():
            # File was deleted externally
            return (
                f"File {path} was deleted since it was last read. "
                f"Read the file again (or create it fresh) before editing."
            )

        stat = resolved.stat()
        # Fast path: mtime unchanged → no need to hash
        if stat.st_mtime_ns == snapshot.mtime_ns and stat.st_size == snapshot.size:
            return None

        # Mtime changed — verify content hash
        current_hash = hashlib.sha256(resolved.read_bytes()).hexdigest()
        if current_hash == snapshot.content_hash:
            # Content same, mtime different (e.g., touch) — update snapshot and allow
            self._snapshots[resolved] = FileSnapshot(
                mtime_ns=stat.st_mtime_ns,
                content_hash=current_hash,
                size=stat.st_size,
            )
            return None

        return (
            f"File {path} was modified externally since it was last read. "
            f"Read the file again to see the current content, then retry the edit."
        )

    def update_after_write(self, path: Path) -> None:
        """Update the tracker after a successful write/edit."""
        self.record_read(path)

    def clear(self) -> None:
        """Clear all tracked state (e.g., on new session)."""
        self._snapshots.clear()

    @property
    def tracked_files(self) -> list[Path]:
        """List of currently tracked file paths."""
        return list(self._snapshots.keys())
