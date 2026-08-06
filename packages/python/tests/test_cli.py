import pytest
import yaml
from typer.testing import CliRunner

from foro import _config
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


TOKEN = "foro_pat_" + "b" * 43


@pytest.fixture
def logged_in(monkeypatch, tmp_path):
    """A machine that already has a stored login for the host under test -
    i.e. every CI run after the first one."""
    monkeypatch.delenv(_config.ENV_TOKEN, raising=False)
    monkeypatch.setenv(_config.ENV_HOST, "127.0.0.1:1")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "config"))

    path = _config.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"127.0.0.1:1": {"token": "foro_pat_" + "a" * 43, "user": "me"}}))


def test_with_token_does_not_lose_the_token_to_the_re_login_prompt(logged_in):
    """`--with-token` is the CI path, and stdin is the token. Confirming
    "already logged in, log in again?" first read that line as the answer,
    rejected it, and aborted at EOF - so re-authenticating a machine that was
    already logged in was impossible without also passing --force.

    The host is unreachable on purpose: getting as far as a rejected *network*
    call is the proof the token was read and used rather than swallowed.
    """
    result = runner.invoke(app, ["auth", "login", "--with-token"], input=TOKEN + "\n")

    assert result.exit_code == 1
    assert "Already logged in" not in result.output
    assert "invalid input" not in result.output
    assert "the token was rejected" in result.output


def test_with_token_still_rejects_a_token_of_the_wrong_shape(logged_in):
    result = runner.invoke(app, ["auth", "login", "--with-token"], input="not-a-token\n")

    assert result.exit_code == 1
    assert "not a foro token" in result.output


def test_the_device_flow_still_asks_before_replacing_a_login(logged_in):
    """Skipping the confirm is scoped to --with-token, not to login at large -
    the interactive path has a terminal to answer on and keeps the guard."""
    result = runner.invoke(app, ["auth", "login"], input="n\n")

    assert result.exit_code == 1
    assert "Already logged in" in result.output
