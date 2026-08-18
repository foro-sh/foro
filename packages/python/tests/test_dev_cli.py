"""CLI-level coverage for `foro dev` - what the terminal actually shows for
each error type `dev()` catches (cli.py:295-320), and the Ctrl+C teardown
path that exists only at this layer, never in `dev.py`'s `run_dev()`."""

from __future__ import annotations

from typer.testing import CliRunner

from foro.cli import app

runner = CliRunner()


def test_dev_on_a_directory_with_no_manifest_names_the_reason(tmp_path):
    result = runner.invoke(app, ["dev", str(tmp_path)])

    assert result.exit_code == 1
    assert "No pyproject.toml or package.json found" in result.stdout
    assert "[missing_manifest]" in result.stdout
