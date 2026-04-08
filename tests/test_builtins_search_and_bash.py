from __future__ import annotations

import asyncio
from pathlib import Path

from taui.agent.session import Session
from taui.config.policies import Policy
from taui.config.settings import Settings
from taui.tools.base import ToolContext
from taui.tools.builtins.bash import BashTool
from taui.tools.builtins.glob import GlobTool
from taui.tools.builtins.grep import GrepTool


def _context(workspace: Path) -> ToolContext:
    settings = Settings()
    settings.policy.auto_approve = ("bash", "glob", "grep")
    settings.policy.confirm = ()
    settings.policy_bash.max_output_bytes = 32
    settings.policy_bash.default_timeout_sec = 1
    return ToolContext(
        working_dir=workspace,
        session=Session(),
        policy=Policy.from_settings(settings),
    )


def test_glob_matches_files(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("print('a')", encoding="utf-8")
    (tmp_path / "b.txt").write_text("x", encoding="utf-8")

    result = asyncio.run(GlobTool().execute({"pattern": "*.py"}, _context(tmp_path)))
    assert result.error is False
    assert "a.py" in result.content


def test_grep_invalid_regex_errors(tmp_path: Path) -> None:
    result = asyncio.run(GrepTool().execute({"pattern": "("}, _context(tmp_path)))
    assert result.error is True
    assert "Invalid regex pattern" in result.content


def test_grep_matches_lines(tmp_path: Path) -> None:
    file_path = tmp_path / "main.py"
    file_path.write_text("alpha\nbeta\nalpha beta\n", encoding="utf-8")

    result = asyncio.run(
        GrepTool().execute(
            {"pattern": "alpha", "path": str(tmp_path), "include": "*.py"},
            _context(tmp_path),
        )
    )
    assert result.error is False
    assert "main.py:1" in result.content
    assert "main.py:3" in result.content


def test_bash_timeout(tmp_path: Path) -> None:
    result = asyncio.run(
        BashTool().execute(
            {"command": 'python3 -c "import time; time.sleep(2)"', "timeout": 1},
            _context(tmp_path),
        )
    )
    assert result.error is True
    assert "timed out" in result.content


def test_bash_output_truncation(tmp_path: Path) -> None:
    result = asyncio.run(
        BashTool().execute(
            {"command": "python3 -c \"print('x'*200)\""},
            _context(tmp_path),
        )
    )
    assert result.error is False
    assert bool(result.metadata and result.metadata.get("truncated")) is True
    assert "[output truncated]" in result.content
