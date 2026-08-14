from __future__ import annotations

import socket
import subprocess
import time
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
    """The footgun this command exists to catch. It surfaces as an immediate
    exit, not a hang - the child gets DEVNULL for stdin."""
    with pytest.raises(DevError, match="foro.run"):
        run_dev(FIXTURES / "stdio-only", timeout=5)


def _dead_on_arrival(tmp_path, port, exit_code=3):
    (tmp_path / "server.py").write_text(f"import sys\nsys.exit({exit_code})\n")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "my-server"\nversion = "0.1.0"\nrequires-python = ">=3.11"\n'
        f'\n[tool.foro]\nport = {port}\n'
    )
    return tmp_path


def test_run_dev_gives_up_as_soon_as_the_server_dies(tmp_path):
    """It used to poll the full timeout regardless."""
    started = time.monotonic()

    with pytest.raises(DevError, match="exited with status 3"):
        run_dev(_dead_on_arrival(tmp_path, 8137), timeout=30)

    assert time.monotonic() - started < 15


def test_a_dead_server_reports_its_exit_status(tmp_path):
    """The old message never mentioned the process had exited, or with what."""
    with pytest.raises(DevError) as exc_info:
        run_dev(_dead_on_arrival(tmp_path, 8138), timeout=30)

    assert "exited with status 3" in str(exc_info.value)
    assert "output is above" in str(exc_info.value)


def test_someone_elses_listener_is_not_mistaken_for_our_server(tmp_path):
    """The probe cannot tell whose listener it found, so a squatter read as
    a healthy server. Refusing the port up front is what fixes that."""
    squatter = socket.socket()
    squatter.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    squatter.bind(("127.0.0.1", 0))
    squatter.listen(8)
    port = squatter.getsockname()[1]

    try:
        with pytest.raises(DevError, match="already in use"):
            run_dev(_dead_on_arrival(tmp_path, port), timeout=30)
    finally:
        squatter.close()


def test_start_server_loads_dotenv(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("DEMO_SECRET=from-dotenv\nPORT=9999\n")
    captured = {}

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return None

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    start_server(tmp_path, "server.py", ".", 8000)

    env = captured["kwargs"]["env"]
    assert env["DEMO_SECRET"] == "from-dotenv"
    # The manifest's real port always wins over a stray PORT in .env -
    # that value is authoritative, not something local config should shadow.
    assert env["PORT"] == "8000"


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
