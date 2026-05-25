"""Global test fixtures.

Redirect CONFIG_PATH to a temp directory so tests never read or write
the real ~/.config/taui/config.toml.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path: Path):
    """Ensure every test uses a throwaway config file."""
    fake_config = tmp_path / "taui" / "config.toml"
    with patch("taui.llm_provider.config.CONFIG_PATH", fake_config):
        yield
