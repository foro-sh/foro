from typer.testing import CliRunner

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


def test_init_stub():
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert "not implemented" in result.stdout


def test_dev_stub():
    result = runner.invoke(app, ["dev"])
    assert result.exit_code == 0
    assert "not implemented" in result.stdout
