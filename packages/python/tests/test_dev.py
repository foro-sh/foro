from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from foro.dev import DevError, run_dev, start_server

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


def _captured_env(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr(subprocess, "Popen", lambda args, **kwargs: captured.update(kwargs))
    start_server(tmp_path, "server.py", ".", 8000)
    return captured["env"]


def test_start_server_suppresses_the_fastmcp_banner(tmp_path, monkeypatch):
    # foro.run() prints foro's own banner instead. Setting it here rather
    # than in-process is what makes it stick: fastmcp reads the variable at
    # import time, which has already happened by the time foro.run() runs.
    monkeypatch.delenv("FASTMCP_SHOW_SERVER_BANNER", raising=False)

    assert _captured_env(tmp_path, monkeypatch)["FASTMCP_SHOW_SERVER_BANNER"] == "false"


def test_start_server_banner_default_yields_to_an_explicit_choice(tmp_path, monkeypatch):
    # A default, not a policy: someone debugging fastmcp itself can ask for
    # its banner back from the shell or from .env.
    monkeypatch.setenv("FASTMCP_SHOW_SERVER_BANNER", "true")
    assert _captured_env(tmp_path, monkeypatch)["FASTMCP_SHOW_SERVER_BANNER"] == "true"

    monkeypatch.delenv("FASTMCP_SHOW_SERVER_BANNER", raising=False)
    (tmp_path / ".env").write_text("FASTMCP_SHOW_SERVER_BANNER=true\n")
    assert _captured_env(tmp_path, monkeypatch)["FASTMCP_SHOW_SERVER_BANNER"] == "true"
