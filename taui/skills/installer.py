"""Install skills from remote sources (git repos, URLs)."""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)


async def install_from_directory(source: Path, target_dir: Path) -> Path:
    """Copy a skill directory into *target_dir*."""
    dest = target_dir / source.name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(source, dest)
    log.info("Installed skill '%s' to %s", source.name, dest)
    return dest


async def install_from_git(
    repo_url: str, skill_path: str, target_dir: Path
) -> Path:
    """Clone a repo and extract a skill subdirectory."""
    import asyncio

    with tempfile.TemporaryDirectory() as tmpdir:
        proc = await asyncio.create_subprocess_exec(
            "git", "clone", "--depth=1", repo_url, tmpdir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"git clone failed: {stderr.decode()}")

        source = Path(tmpdir) / skill_path
        if not (source / "SKILL.md").is_file():
            raise FileNotFoundError(
                f"No SKILL.md found at {skill_path} in {repo_url}"
            )
        return await install_from_directory(source, target_dir)
