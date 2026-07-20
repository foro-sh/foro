from typer.testing import CliRunner

from foro.cli import app

runner = CliRunner()


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip()


def test_check_stub():
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 0
    assert "not implemented" in result.stdout


def test_init_stub():
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert "not implemented" in result.stdout


def test_dev_stub():
    result = runner.invoke(app, ["dev"])
    assert result.exit_code == 0
    assert "not implemented" in result.stdout
