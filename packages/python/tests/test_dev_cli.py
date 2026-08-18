"""CLI-level coverage for `foro dev` - what the terminal actually shows for
each error type `dev()` catches (cli.py:295-320), and the Ctrl+C teardown
path that exists only at this layer, never in `dev.py`'s `run_dev()`."""

from __future__ import annotations

from typer.testing import CliRunner

import foro.cli as cli_module
from foro.cli import app
from foro.dev import DevError

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
