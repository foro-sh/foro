"""CLI-level coverage for `foro dev` - what the terminal actually shows for
each error type `dev()` catches (cli.py:295-320), and the Ctrl+C teardown
path that exists only at this layer, never in `dev.py`'s `run_dev()`."""

from __future__ import annotations

import subprocess

from typer.testing import CliRunner

import foro.cli as cli_module
from foro.cli import app
from foro.dev import DevError, DevResult

runner = CliRunner()


def test_dev_on_a_directory_with_no_manifest_names_the_reason(tmp_path):
    result = runner.invoke(app, ["dev", str(tmp_path)])

    assert result.exit_code == 1
    assert "No pyproject.toml or package.json found" in result.stdout
    assert "[missing_manifest]" in result.stdout


def test_dev_reports_an_unhealthy_server_without_a_traceback(tmp_path, monkeypatch):
    def fake_run_dev(path):
        raise DevError("server never opened port 8000 within 60s.")

    monkeypatch.setattr(cli_module, "run_dev", fake_run_dev)

    result = runner.invoke(app, ["dev", str(tmp_path)])

    assert result.exit_code == 1
    assert "server never opened port 8000" in result.stdout
    assert "Traceback" not in result.stdout


class _FakeProcess:
    """A process whose `wait()` acts like Ctrl+C landed mid-run: the no-arg
    call (blocking on the running server) raises KeyboardInterrupt, while the
    timed call (the teardown that follows) behaves however the test needs."""

    def __init__(self, kill_needed: bool = False) -> None:
        self.terminated = False
        self.killed = False
        self._kill_needed = kill_needed

    def wait(self, timeout=None):
        if timeout is None:
            raise KeyboardInterrupt
        if self._kill_needed:
            raise subprocess.TimeoutExpired(cmd="uv", timeout=timeout)
        return 0

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True


def test_ctrl_c_terminates_the_server(tmp_path, monkeypatch):
    fake = _FakeProcess()
    monkeypatch.setattr(
        cli_module, "run_dev", lambda path: (fake, DevResult(port=8000, tool_names=["add"]))
    )

    result = runner.invoke(app, ["dev", str(tmp_path)])

    assert result.exit_code == 0
    assert fake.terminated
    assert not fake.killed
