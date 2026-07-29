from typer.testing import CliRunner

from foro._manifest import DEFAULT_PORT, DEFAULT_PYTHON_VERSION
from foro.cli import app

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
