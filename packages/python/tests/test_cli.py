from typer.testing import CliRunner

from foro._manifest import DEFAULT_PORT, DEFAULT_PYTHON_VERSION
from foro.cli import app
from foro.dev import DevResult

runner = CliRunner()


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip()


def test_check_passes_valid_project(tmp_path):
    (tmp_path / "foro.yaml").write_text("name: my-server\nentrypoint: server.py\n")
    (tmp_path / "server.py").write_text("# mcp server\n")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "my-server"\n')

    result = runner.invoke(app, ["check", str(tmp_path)])

    assert result.exit_code == 0
    assert "would pass" in result.stdout


def test_check_fails_invalid_project(tmp_path):
    (tmp_path / "foro.yaml").write_text("name: My_Server\nentrypoint: server.py\n")

    result = runner.invoke(app, ["check", str(tmp_path)])

    assert result.exit_code == 1
    assert "invalid_name" in result.stdout


def test_dev_once_stops_the_server_instead_of_waiting(monkeypatch):
    """`--once` is what makes `dev` runnable by an agent at all: the default
    form blocks on `process.wait()` until Ctrl+C, which an agent can only
    escape by timing out. The fake refuses an unbounded `wait()`, so this
    fails if `--once` ever falls through to the blocking path - a plain
    exit-code assertion wouldn't, since a fake process returns instantly."""

    class FakeProcess:
        terminated = False

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            assert timeout is not None, "--once must not block on process.wait()"
            return 0

    process = FakeProcess()
    monkeypatch.setattr(
        "foro.cli.run_dev",
        lambda path: (process, DevResult(port=DEFAULT_PORT, tool_names=["add"])),
    )

    result = runner.invoke(app, ["dev", "--once"])

    assert result.exit_code == 0, result.exception or result.stdout
    assert "would pass" in result.stdout
    assert "add" in result.stdout
    assert process.terminated


def test_init_yes_answers_every_prompt_with_its_default(tmp_path, monkeypatch):
    """No stdin is supplied, so a surviving prompt aborts the run - which is
    exactly what `--yes` exists to prevent when CI or an agent drives init."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "server.py").write_text("# mcp server\n")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "my-server"\n')

    result = runner.invoke(app, ["init", "--yes"])

    assert result.exit_code == 0, result.stdout
    manifest = (tmp_path / "foro.yaml").read_text()
    assert "entrypoint: server.py" in manifest
    assert f"python_version: '{DEFAULT_PYTHON_VERSION}'" in manifest
    assert f"port: {DEFAULT_PORT}" in manifest
