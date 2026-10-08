import os

import pytest
import yaml
from typer.testing import CliRunner

from foro import _config
from foro._manifest import DEFAULT_PORT, DEFAULT_RUNTIME, DEFAULT_RUNTIME_VERSIONS
from foro.cli import app
from foro.dev import DevResult

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
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "my-server"\n')

    result = runner.invoke(app, ["check", str(tmp_path)])

    assert result.exit_code == 1
    assert "invalid_entrypoint" in result.stdout


def test_dev_once_stops_the_server_instead_of_waiting(monkeypatch):
    """`--once` must call `wait(timeout=...)`, not block on `wait()`."""

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
    """`--yes` must not prompt; no stdin is supplied."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "server.py").write_text("# mcp server\n")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "my-server"\n')

    result = runner.invoke(app, ["init", "--yes"])

    assert result.exit_code == 0, result.stdout
    assert "nothing to configure" in result.stdout
    assert "[tool.foro]" not in (tmp_path / "pyproject.toml").read_text()


TOKEN = "foro_pat_" + "b" * 43


@pytest.fixture
def logged_in(monkeypatch, tmp_path):
    """Stored login for 127.0.0.1:1."""
    monkeypatch.delenv(_config.ENV_TOKEN, raising=False)
    monkeypatch.setenv(_config.ENV_HOST, "127.0.0.1:1")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "config"))

    path = _config.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"127.0.0.1:1": {"token": "foro_pat_" + "a" * 43, "user": "me"}}))
    if os.name != "nt":
        path.chmod(0o600)
    return path


@pytest.fixture
def logged_out(monkeypatch, tmp_path):
    """No stored login."""
    monkeypatch.delenv(_config.ENV_TOKEN, raising=False)
    monkeypatch.setenv(_config.ENV_HOST, "127.0.0.1:1")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "config"))


def test_with_token_does_not_lose_the_token_to_the_re_login_prompt(logged_in):
    """`--with-token` must not treat stdin as a confirm answer."""
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
    """Closed stdin must not raise EOFError out of `foro auth login`."""
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

    result = runner.invoke(app, ["auth", "login"], input="")

    assert not isinstance(result.exception, EOFError)
    assert result.exit_code == 1
    assert grant.verification_uri_complete in result.output
    assert "denied" in result.output
    assert opened == []


def test_the_device_flow_still_asks_before_replacing_a_login(logged_in):
    """Interactive login still confirms before replacing a stored token."""
    result = runner.invoke(app, ["auth", "login"], input="n\n")

    assert result.exit_code == 1
    assert "Already logged in" in result.output


@pytest.mark.parametrize("command", [["auth", "status"], ["auth", "logout"], ["auth", "token"]])
def test_auth_commands_require_a_login(logged_out, command):
    """status, logout, and token require a stored login."""
    result = runner.invoke(app, command)

    assert result.exit_code == 1
    assert "not logged in to 127.0.0.1:1" in result.stdout


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits only")
def test_auth_status_warns_when_config_file_is_insecure(logged_in, monkeypatch):
    import foro.cli as cli_module
    from foro.auth import Identity

    logged_in.chmod(0o644)
    monkeypatch.setattr(cli_module, "fetch_identity", lambda host, token: Identity(user="me", workspaces=[]))

    result = runner.invoke(app, ["auth", "status"])

    assert result.exit_code == 0
    assert f"warning: {logged_in} is readable by other users - `chmod 600` it" in result.stdout
    assert "✓ Logged in as me" in result.stdout


def test_auth_status_does_not_warn_when_config_file_is_secure(logged_in, monkeypatch):
    """No warning when the config file is 0600."""
    import foro.cli as cli_module
    from foro.auth import Identity

    monkeypatch.setattr(cli_module, "fetch_identity", lambda host, token: Identity(user="me", workspaces=[]))

    result = runner.invoke(app, ["auth", "status"])

    assert result.exit_code == 0
    assert "readable by other users" not in result.stdout


def test_auth_logout_deletes_the_local_token_when_revoke_fails(logged_in):
    """Logout deletes the local file even when server-side revoke fails."""
    result = runner.invoke(app, ["auth", "logout"], input="y\n")

    assert result.exit_code == 0
    assert "could not revoke server-side" in result.output
    assert "✓ Logged out locally" in result.output
    assert _config.load("127.0.0.1:1") is None
    assert not logged_in.exists()


def test_auth_logout_leaves_the_token_alone_when_declined(logged_in):
    result = runner.invoke(app, ["auth", "logout"], input="n\n")

    assert result.exit_code == 1
    assert logged_in.exists()


def test_auth_token_prints_exactly_the_stored_token(logged_in):
    """stdout is exactly the token, so `$(foro auth token)` is safe."""
    result = runner.invoke(app, ["auth", "token"])

    assert result.exit_code == 0
    assert result.stdout == "foro_pat_" + "a" * 43 + "\n"


def test_detach_prints_the_mcp_endpoint(logged_in, tmp_path, monkeypatch):
    """`--detach` must print the client URL, not the origin."""
    from foro.deploy import Started

    started = Started(
        slug="swift-harbor-a3f2",
        deployment_id="a1b2c3d4eeeeeeee",
        url="https://swift-harbor-a3f2.foro.sh",
        created=False,
    )
    monkeypatch.setattr("foro.cli.deploy_project", lambda *a, **k: started)

    result = runner.invoke(app, ["deploy", str(tmp_path), "--detach", "--skip-check"])

    assert result.exit_code == 0, result.stdout
    assert "https://swift-harbor-a3f2.foro.sh/mcp" in result.stdout


# --- Workspaces (foro-sh/foro#129): a token reaches every workspace; each
# request names the one it acts in with X-Foro-Workspace.

ACME = ("11111111-1111-1111-1111-111111111111", "acme")
GLOBEX = ("22222222-2222-2222-2222-222222222222", "globex")


@pytest.fixture
def two_workspaces(monkeypatch):
    import foro.cli as cli_module
    from foro.auth import Identity, Workspace

    identity = Identity(user="me", workspaces=[Workspace(*ACME), Workspace(*GLOBEX)])
    monkeypatch.setattr(cli_module, "fetch_identity", lambda host, token: identity)
    return identity


@pytest.fixture
def sent_workspaces(monkeypatch):
    """The X-Foro-Workspace each `list_projects` call would carry."""
    import foro.cli as cli_module
    from foro import _api

    sent = []

    def fake_list(host, token):
        sent.append(_api.current_workspace())
        return []

    monkeypatch.setattr(cli_module, "list_projects", fake_list)
    return sent


def test_workspace_use_stores_the_default_by_name(logged_in, two_workspaces, sent_workspaces):
    result = runner.invoke(app, ["workspace", "use", "GLOBEX"])

    assert result.exit_code == 0, result.output
    assert "now act in globex" in result.stdout
    loaded = _config.load("127.0.0.1:1")
    assert (loaded.workspace_id, loaded.workspace_name) == GLOBEX

    runner.invoke(app, ["projects"])
    assert sent_workspaces == [GLOBEX[0]]


def test_workspace_use_rejects_an_unknown_workspace(logged_in, two_workspaces):
    result = runner.invoke(app, ["workspace", "use", "initech"])

    assert result.exit_code == 1
    assert "no workspace 'initech' - yours: acme, globex" in result.stdout


def test_workspace_list_marks_the_default(logged_in, two_workspaces):
    runner.invoke(app, ["workspace", "use", ACME[1]])
    result = runner.invoke(app, ["workspace", "list"])

    assert result.exit_code == 0
    assert f"* acme" in result.stdout
    assert f"  globex" in result.stdout


def test_the_flag_overrides_the_default_for_one_command(logged_in, two_workspaces, sent_workspaces):
    runner.invoke(app, ["workspace", "use", "acme"])
    runner.invoke(app, ["--workspace", "globex", "projects"])
    runner.invoke(app, ["projects"])

    assert sent_workspaces == [GLOBEX[0], ACME[0]]


def test_the_env_var_selects_a_workspace(logged_in, two_workspaces, sent_workspaces, monkeypatch):
    monkeypatch.setenv(_config.ENV_WORKSPACE, GLOBEX[0])
    runner.invoke(app, ["projects"])

    assert sent_workspaces == [GLOBEX[0]]


def test_no_default_sends_no_workspace(logged_in, sent_workspaces):
    runner.invoke(app, ["projects"])

    assert sent_workspaces == [None]


def test_a_linked_directory_acts_in_its_project_workspace(logged_in, sent_workspaces, tmp_path, monkeypatch):
    import foro.cli as cli_module
    from foro import _api, _project_link

    _project_link.save(tmp_path, _project_link.ProjectLink(host="127.0.0.1:1", slug="s", workspace=GLOBEX[0]))
    seen = []
    monkeypatch.setattr(
        cli_module, "get_project", lambda host, token, slug: seen.append(_api.current_workspace()) or {"url": "u"}
    )
    monkeypatch.setattr(cli_module.webbrowser, "open", lambda url: None)

    runner.invoke(app, ["open", str(tmp_path)])

    assert seen == [GLOBEX[0]]


def test_login_asks_for_a_default_when_there_are_several(logged_out, two_workspaces, monkeypatch):
    import foro.cli as cli_module

    monkeypatch.setattr(cli_module, "_run_device_flow", lambda host: TOKEN)
    result = runner.invoke(app, ["auth", "login"], input="2\n")

    assert result.exit_code == 0, result.output
    assert "(workspace: globex)" in result.stdout
    assert _config.load("127.0.0.1:1").workspace_id == GLOBEX[0]


def test_login_with_token_leaves_several_unchosen(logged_out, two_workspaces):
    result = runner.invoke(app, ["auth", "login", "--with-token"], input=TOKEN + "\n")

    assert result.exit_code == 0, result.output
    assert "foro workspace use" in result.stdout
    assert _config.load("127.0.0.1:1").workspace_id is None
