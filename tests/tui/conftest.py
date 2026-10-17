"""Tests for the `finger` TUI (tui/goodix550c_tui). They need textual; the rest of the repo's
suite does not, so everything here skips cleanly when it is missing.

Run:  build/tui-venv/bin/python -m pytest tests/tui
(venv: python3 -m venv build/tui-venv && build/tui-venv/bin/pip install textual==2.1.2 rich==13.9.4 pytest)
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tui"))


def pytest_ignore_collect(collection_path, config):
    try:
        import textual  # noqa: F401
    except ImportError:
        return True
    return None
