from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from foro.dev import DevError, run_dev, start_server, stop

FIXTURES = Path(__file__).parent / "fixtures"


def test_run_dev_succeeds_against_a_real_foro_run_server():
    process, result = run_dev(FIXTURES / "minimal-fastmcp", timeout=20)
    try:
        assert result.port == 8000
        assert "add" in result.tool_names
    finally:
        stop(process)


def test_run_dev_raises_on_stdio_only_server():
    with pytest.raises(DevError, match="never opened port"):
        run_dev(FIXTURES / "stdio-only", timeout=5)


def test_start_server_loads_dotenv(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("DEMO_SECRET=from-dotenv\nMCP_PORT=9999\n")
    captured = {}

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return None

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    start_server(tmp_path, "server.py", ".", 8000)

    env = captured["kwargs"]["env"]
    assert env["DEMO_SECRET"] == "from-dotenv"
    # The manifest's real port always wins over a stray MCP_PORT in .env -
    # that value is authoritative, not something local config should shadow.
    assert env["MCP_PORT"] == "8000"
