import os

import pytest
import yaml
from typer.testing import CliRunner

from foro import _config
from foro._manifest import DEFAULT_PORT, DEFAULT_RUNTIME, DEFAULT_RUNTIME_VERSIONS
from foro.cli import app

runner = CliRunner()


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip()


def test_check_passes_valid_project(tmp_path):
    (tmp_path / "server.py").write_text("# mcp server\n")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "my-server"\n')

    result = runner.invoke(app, ["check", str(tmp_path)])

    assert result.exit_code == 0
    assert "would pass" in result.stdout


def test_check_fails_invalid_project(tmp_path):
    # A Python project whose entry file is none of the names foro looks for
    # and which never says where it is.
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "my-server"\n')

    result = runner.invoke(app, ["check", str(tmp_path)])

    assert result.exit_code == 1
    assert "invalid_entrypoint" in result.stdout


def test_init_yes_answers_every_prompt_with_its_default(tmp_path, monkeypatch):
    """No stdin is supplied, so a surviving prompt aborts the run - which is
    exactly what `--yes` exists to prevent when CI or an agent drives init."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "server.py").write_text("# mcp server\n")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "my-server"\n')

    result = runner.invoke(app, ["init", "--yes"])

    assert result.exit_code == 0, result.stdout
    # Every default answer is one the platform infers, so there is nothing to
    # write down - that is the point of the defaults, not a failure to act.
    assert "nothing to configure" in result.stdout
    assert "[tool.foro]" not in (tmp_path / "pyproject.toml").read_text()


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
    # write_text takes the default umask, which is usually group/world
    # readable - narrow it so tests start from the secure baseline the real
    # `save()` produces, and opt into the insecure case explicitly.
    if os.name != "nt":
        path.chmod(0o600)
    return path


@pytest.fixture
def logged_out(monkeypatch, tmp_path):
    """A machine that has never logged in to the host under test."""
    monkeypatch.delenv(_config.ENV_TOKEN, raising=False)
    monkeypatch.setenv(_config.ENV_HOST, "127.0.0.1:1")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "config"))


def test_with_token_does_not_lose_the_token_to_the_re_login_prompt(logged_in):
    """stdin is the token, and the re-login confirm used to eat it as its
    answer. The host is unreachable on purpose - reaching a rejected network
    call proves the token was read rather than swallowed.
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


def test_the_device_flow_does_not_die_on_a_closed_stdin(monkeypatch, tmp_path):
    """`input()` ran unconditionally and its EOFError escaped every handler -
    what `foro auth login` under nohup or in a container looked like."""
    monkeypatch.delenv(_config.ENV_TOKEN, raising=False)
    monkeypatch.setenv(_config.ENV_HOST, "127.0.0.1:1")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    import foro.cli as cli_module
    from foro.auth import AuthError, DeviceGrant

    grant = DeviceGrant(
        device_code="dev-code",
        user_code="7A2F-K9QP",
        verification_uri="https://foro.sh/cli",
        verification_uri_complete="https://foro.sh/cli?code=7A2F-K9QP",
        expires_in=900,
        interval=5,
    )
    monkeypatch.setattr(cli_module, "start_device_flow", lambda host, label: grant)
    opened = []
    monkeypatch.setattr(cli_module, "_open_browser", opened.append)

    def denied(host, grant, on_wait=None):
        raise AuthError("authorization was denied in the browser")

    monkeypatch.setattr(cli_module, "poll_for_token", denied)

    # CliRunner hands the command a non-tty stdin, which is the case at issue.
    result = runner.invoke(app, ["auth", "login"], input="")

    assert not isinstance(result.exception, EOFError)
    assert result.exit_code == 1
    # It got all the way to polling, and said where to authorize on the way.
    assert grant.verification_uri_complete in result.output
    assert "denied" in result.output
    # No terminal means no browser worth opening - the URL is on screen.
    assert opened == []


def test_the_device_flow_still_asks_before_replacing_a_login(logged_in):
    """Skipping the confirm is scoped to --with-token, not login at large."""
    result = runner.invoke(app, ["auth", "login"], input="n\n")

    assert result.exit_code == 1
    assert "Already logged in" in result.output
