"""CLI output and Ctrl+C teardown for `foro dev`."""

from __future__ import annotations

import subprocess

import pytest

from typer.testing import CliRunner

import foro.cli as cli_module
from foro.cli import app
from foro.dev import DevError, DevResult

runner = CliRunner()


@pytest.fixture(autouse=True)
def _no_real_inspector(monkeypatch):
    monkeypatch.setattr(cli_module, "start_inspector", lambda port: _FakeProcess())


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
    """`wait()` with no timeout raises KeyboardInterrupt."""

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


def test_ctrl_c_kills_a_server_that_ignores_terminate(tmp_path, monkeypatch):
    """If terminate() times out, kill() must run."""
    fake = _FakeProcess(kill_needed=True)
    monkeypatch.setattr(
        cli_module, "run_dev", lambda path: (fake, DevResult(port=8000, tool_names=["add"]))
    )

    result = runner.invoke(app, ["dev", str(tmp_path)])

    assert result.exit_code == 0
    assert fake.terminated
    assert fake.killed


def test_dev_lists_no_tools_as_none(tmp_path, monkeypatch):
    fake = _FakeProcess()
    monkeypatch.setattr(
        cli_module, "run_dev", lambda path: (fake, DevResult(port=8000, tool_names=[]))
    )

    result = runner.invoke(app, ["dev", str(tmp_path)])

    assert "Tools: (none)" in result.stdout


def test_inspector_starts_on_the_server_port_and_stops_with_it(tmp_path, monkeypatch):
    server, inspector, ports = _FakeProcess(), _FakeProcess(), []
    monkeypatch.setattr(
        cli_module, "run_dev", lambda path: (server, DevResult(port=8123, tool_names=["add"]))
    )
    monkeypatch.setattr(cli_module, "start_inspector", lambda port: ports.append(port) or inspector)

    runner.invoke(app, ["dev", str(tmp_path)])

    assert ports == [8123]
    assert server.terminated and inspector.terminated


def test_once_and_no_inspect_skip_the_inspector(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cli_module, "run_dev", lambda path: (_FakeProcess(), DevResult(port=8000, tool_names=[]))
    )
    monkeypatch.setattr(
        cli_module, "start_inspector", lambda port: pytest.fail("inspector must not start")
    )

    assert runner.invoke(app, ["dev", str(tmp_path), "--once"]).exit_code == 0
    assert runner.invoke(app, ["dev", str(tmp_path), "--no-inspect"]).exit_code == 0


def test_missing_npx_warns_and_keeps_the_server_running(tmp_path, monkeypatch):
    from foro._proc import MissingToolError

    server = _FakeProcess()
    monkeypatch.setattr(
        cli_module, "run_dev", lambda path: (server, DevResult(port=8000, tool_names=[]))
    )

    def no_npx(port):
        raise MissingToolError("npx")

    monkeypatch.setattr(cli_module, "start_inspector", no_npx)

    result = runner.invoke(app, ["dev", str(tmp_path)])

    assert result.exit_code == 0
    assert "no inspector" in result.stdout
    assert server.terminated


@pytest.mark.parametrize("version, ok", [("v22.19.0", True), ("v24.1.0", True), ("v22.18.9", False), ("v20.11.0", False)])
def test_inspector_needs_node_22_19(monkeypatch, version, ok):
    import foro.dev as dev_module

    monkeypatch.setattr(
        dev_module, "run", lambda argv: subprocess.CompletedProcess(argv, 0, stdout=version + "\n")
    )
    monkeypatch.setattr(dev_module, "popen", lambda argv, **kw: "started")

    if ok:
        assert dev_module.start_inspector(8000) == "started"
    else:
        with pytest.raises(dev_module.InspectorUnavailable, match="22.19"):
            dev_module.start_inspector(8000)
