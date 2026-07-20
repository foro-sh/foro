from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from foro.dev import DevError, run_dev

FIXTURES = Path(__file__).parent / "fixtures"


def test_run_dev_succeeds_against_a_real_foro_run_server():
    process, result = run_dev(FIXTURES / "minimal-fastmcp", timeout=20)
    try:
        assert result.port == 8000
        assert "add" in result.tool_names
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def test_run_dev_raises_on_stdio_only_server():
    with pytest.raises(DevError, match="never opened port"):
        run_dev(FIXTURES / "stdio-only", timeout=5)
