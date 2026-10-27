import os

import pytest
import yaml
from typer.testing import CliRunner

from foro import _config, _project_link
from foro._api import ApiError
from foro._manifest import DEFAULT_PORT, DEFAULT_RUNTIME, DEFAULT_RUNTIME_VERSIONS
from foro.cli import app
from foro.dev import DevResult

runner = CliRunner()


@pytest.fixture(autouse=True)
def _reset_workspace_override():
    """`--workspace` sets a module global; a test invoking `_resolve_workspace`
    directly (not through `app`) must not see another test's leftover value."""
    import foro.cli as cli_module

    cli_module._workspace_override = None
    yield
    cli_module._workspace_override = None


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


def test_login_with_a_single_workspace_sets_it_as_default_without_prompting(logged_out, monkeypatch):
    import foro.cli as cli_module
    from foro.auth import Identity, WorkspaceRef

    monkeypatch.setattr(
        cli_module,
        "fetch_identity",
        lambda host, token: Identity(
            user="me",
            workspace=WorkspaceRef(id="w-1", name="acme"),
            workspaces=[WorkspaceRef(id="w-1", name="acme")],
        ),
    )

    result = runner.invoke(app, ["auth", "login", "--with-token"], input=TOKEN + "\n")

    assert result.exit_code == 0, result.output
    assert "workspace: acme" in result.output.lower()
    assert _config.load("127.0.0.1:1").workspace == "w-1"


def test_login_with_several_workspaces_and_with_token_sets_no_default(logged_out, monkeypatch):
    """--with-token is unattended; it must not prompt and must not guess."""
    import foro.cli as cli_module
    from foro.auth import Identity, WorkspaceRef

    monkeypatch.setattr(
        cli_module,
        "fetch_identity",
        lambda host, token: Identity(
            user="me",
            workspace=None,
            workspaces=[WorkspaceRef(id="w-1", name="acme"), WorkspaceRef(id="w-2", name="umbrella")],
        ),
    )

    result = runner.invoke(app, ["auth", "login", "--with-token"], input=TOKEN + "\n")

    assert result.exit_code == 0, result.output
    assert "workspace:" not in result.output.lower()
    assert _config.load("127.0.0.1:1").workspace is None


def test_reauth_with_token_keeps_an_existing_valid_default(logged_in, monkeypatch):
    """A non-interactive re-login must not wipe a working default it can't re-derive."""
    import foro.cli as cli_module
    from foro.auth import Identity, WorkspaceRef

    _with_default_workspace(logged_in, workspace_id="w-2")
    monkeypatch.setattr(
        cli_module,
        "fetch_identity",
        lambda host, token: Identity(
            user="me",
            workspace=None,
            workspaces=[WorkspaceRef(id="w-1", name="acme"), WorkspaceRef(id="w-2", name="umbrella")],
        ),
    )

    result = runner.invoke(app, ["auth", "login", "--with-token", "--force"], input=TOKEN + "\n")

    assert result.exit_code == 0, result.output
    assert _config.load("127.0.0.1:1").workspace == "w-2"


def test_reauth_with_token_drops_a_default_that_is_no_longer_a_member(logged_in, monkeypatch):
    import foro.cli as cli_module
    from foro.auth import Identity, WorkspaceRef

    _with_default_workspace(logged_in, workspace_id="w-removed")
    monkeypatch.setattr(
        cli_module,
        "fetch_identity",
        lambda host, token: Identity(
            user="me",
            workspace=None,
            workspaces=[WorkspaceRef(id="w-1", name="acme"), WorkspaceRef(id="w-2", name="umbrella")],
        ),
    )

    result = runner.invoke(app, ["auth", "login", "--with-token", "--force"], input=TOKEN + "\n")

    assert result.exit_code == 0, result.output
    assert _config.load("127.0.0.1:1").workspace is None


def test_login_with_several_workspaces_prompts_and_stores_the_pick(monkeypatch, tmp_path):
    """The interactive device flow still prompts to pick a default."""
    import foro.cli as cli_module
    from foro.auth import DeviceGrant, Identity, WorkspaceRef

    monkeypatch.delenv(_config.ENV_TOKEN, raising=False)
    monkeypatch.setenv(_config.ENV_HOST, "127.0.0.1:1")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    grant = DeviceGrant(
        device_code="dev-code",
        user_code="UC",
        verification_uri="https://foro.sh/cli",
        verification_uri_complete="https://foro.sh/cli?code=UC",
        expires_in=900,
        interval=5,
    )
    monkeypatch.setattr(cli_module, "start_device_flow", lambda host, label: grant)
    monkeypatch.setattr(cli_module, "poll_for_token", lambda host, grant, on_wait=None: {"access_token": TOKEN})
    monkeypatch.setattr(
        cli_module,
        "fetch_identity",
        lambda host, token: Identity(
            user="me",
            workspace=None,
            workspaces=[WorkspaceRef(id="w-1", name="acme"), WorkspaceRef(id="w-2", name="umbrella")],
        ),
    )

    result = runner.invoke(app, ["auth", "login"], input="2\n")

    assert result.exit_code == 0, result.output
    assert "workspace: umbrella" in result.output.lower()
    assert _config.load("127.0.0.1:1").workspace == "w-2"


def _with_default_workspace(logged_in, workspace_id="w-1"):
    data = yaml.safe_load(logged_in.read_text())
    data["127.0.0.1:1"]["workspace"] = workspace_id
    logged_in.write_text(yaml.safe_dump(data))


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits only")
def test_auth_status_warns_when_config_file_is_insecure(logged_in, monkeypatch):
    import foro.cli as cli_module
    from foro.auth import Identity, WorkspaceRef

    _with_default_workspace(logged_in)
    logged_in.chmod(0o644)
    monkeypatch.setattr(
        cli_module,
        "fetch_identity",
        lambda host, token: Identity(
            user="me", workspace=None, workspaces=[WorkspaceRef(id="w-1", name="acme")]
        ),
    )

    result = runner.invoke(app, ["auth", "status"])

    assert result.exit_code == 0
    assert f"warning: {logged_in} is readable by other users - `chmod 600` it" in result.stdout
    assert "✓ Logged in as me" in result.stdout
    assert "Workspace: acme" in result.stdout


def test_auth_status_does_not_warn_when_config_file_is_secure(logged_in, monkeypatch):
    """No warning when the config file is 0600."""
    import foro.cli as cli_module
    from foro.auth import Identity

    monkeypatch.setattr(
        cli_module, "fetch_identity", lambda host, token: Identity(user="me", workspace=None, workspaces=[])
    )

    result = runner.invoke(app, ["auth", "status"])

    assert result.exit_code == 0
    assert "readable by other users" not in result.stdout


def test_auth_status_flags_a_default_workspace_that_no_longer_exists(logged_in, monkeypatch):
    import foro.cli as cli_module
    from foro.auth import Identity

    _with_default_workspace(logged_in, workspace_id="gone")
    monkeypatch.setattr(
        cli_module, "fetch_identity", lambda host, token: Identity(user="me", workspace=None, workspaces=[])
    )

    result = runner.invoke(app, ["auth", "status"])

    assert result.exit_code == 0
    assert "gone (not found - run `foro workspace use`)" in result.stdout


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


def test_workspace_list_marks_the_stored_default(logged_in, monkeypatch):
    import foro.cli as cli_module
    from foro.auth import WorkspaceRef

    _with_default_workspace(logged_in, workspace_id="w-2")
    monkeypatch.setattr(
        cli_module,
        "list_workspaces",
        lambda host, token: [WorkspaceRef(id="w-1", name="acme"), WorkspaceRef(id="w-2", name="umbrella")],
    )

    result = runner.invoke(app, ["workspace", "list"])

    assert result.exit_code == 0, result.output
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines[0].startswith("  acme")
    assert lines[1].startswith("* umbrella")


def test_workspace_use_resolves_by_name_and_stores_the_id(logged_in, monkeypatch):
    import foro.cli as cli_module
    from foro.auth import WorkspaceRef

    monkeypatch.setattr(
        cli_module,
        "list_workspaces",
        lambda host, token: [WorkspaceRef(id="w-1", name="acme"), WorkspaceRef(id="w-2", name="umbrella")],
    )

    result = runner.invoke(app, ["workspace", "use", "umbrella"])

    assert result.exit_code == 0, result.output
    assert "default workspace set to umbrella" in result.output
    assert _config.load("127.0.0.1:1").workspace == "w-2"


def test_workspace_use_accepts_an_id_too(logged_in, monkeypatch):
    import foro.cli as cli_module
    from foro.auth import WorkspaceRef

    monkeypatch.setattr(cli_module, "list_workspaces", lambda host, token: [WorkspaceRef(id="w-1", name="acme")])

    result = runner.invoke(app, ["workspace", "use", "w-1"])

    assert result.exit_code == 0, result.output
    assert _config.load("127.0.0.1:1").workspace == "w-1"


def test_workspace_use_refuses_a_name_matching_nothing(logged_in, monkeypatch):
    import foro.cli as cli_module
    from foro.auth import WorkspaceRef

    monkeypatch.setattr(cli_module, "list_workspaces", lambda host, token: [WorkspaceRef(id="w-1", name="acme")])

    result = runner.invoke(app, ["workspace", "use", "nope"])

    assert result.exit_code == 1
    assert "no workspace matches" in result.output


def test_workspace_use_with_an_env_token_is_refused(monkeypatch, tmp_path):
    """There is no stored login to attach a default workspace to."""
    monkeypatch.setenv(_config.ENV_TOKEN, TOKEN)
    monkeypatch.setenv(_config.ENV_HOST, "127.0.0.1:1")

    result = runner.invoke(app, ["workspace", "use", "acme"])

    assert result.exit_code == 1
    assert "no stored login" in result.output


def test_global_workspace_flag_resolves_by_name_before_the_api_call(logged_in, monkeypatch):
    """`--workspace` is a global option; it must resolve and reach list_projects."""
    import foro.cli as cli_module
    from foro.auth import WorkspaceRef

    monkeypatch.setattr(
        cli_module, "list_workspaces", lambda host, token: [WorkspaceRef(id="w-2", name="umbrella")]
    )
    captured = {}

    def fake_list_projects(host, token, *, workspace=None):
        captured["workspace"] = workspace
        return []

    monkeypatch.setattr(cli_module, "list_projects", fake_list_projects)

    result = runner.invoke(app, ["--workspace", "umbrella", "projects"])

    assert result.exit_code == 0, result.output
    assert captured["workspace"] == "w-2"


def test_workspace_flag_must_precede_the_subcommand(logged_in):
    """A root option - Typer/Click parses it only before the subcommand name."""
    result = runner.invoke(app, ["projects", "--workspace", "acme"])

    assert result.exit_code != 0
    assert "No such option" in result.output


def test_projects_show_ignores_the_directorys_link_when_project_is_overridden(
    logged_in, tmp_path, monkeypatch
):
    import foro.cli as cli_module

    _project_link.save(
        tmp_path, _project_link.ProjectLink(host="127.0.0.1:1", slug="old-slug", workspace="w-old")
    )
    captured = {}

    def fake_get_project(host, token, slug, *, workspace=None):
        captured["workspace"] = workspace
        return {"slug": slug, "name": None, "status": "live", "source": "upload", "url": "https://x.foro.sh"}

    monkeypatch.setattr(cli_module, "get_project", fake_get_project)
    monkeypatch.setattr(cli_module, "list_deployments", lambda host, token, slug, *, workspace=None: [])

    result = runner.invoke(app, ["projects", "show", str(tmp_path), "--project", "other-slug"])

    assert result.exit_code == 0, result.output
    assert captured["workspace"] is None


def test_open_ignores_the_directorys_link_when_project_is_overridden(logged_in, tmp_path, monkeypatch):
    import foro.cli as cli_module

    _project_link.save(
        tmp_path, _project_link.ProjectLink(host="127.0.0.1:1", slug="old-slug", workspace="w-old")
    )
    captured = {}

    def fake_get_project(host, token, slug, *, workspace=None):
        captured["workspace"] = workspace
        return {"slug": slug, "url": "https://x.foro.sh"}

    monkeypatch.setattr(cli_module, "get_project", fake_get_project)
    monkeypatch.setattr(cli_module.webbrowser, "open", lambda url: None)

    result = runner.invoke(app, ["open", str(tmp_path), "--project", "other-slug"])

    assert result.exit_code == 0, result.output
    assert captured["workspace"] is None


def test_bare_projects_list_uses_the_current_directorys_linked_workspace(logged_in, tmp_path, monkeypatch):
    """A linked directory's workspace comes ahead of the stored default,
    even for the bare list (no path argument of its own - uses cwd)."""
    import foro.cli as cli_module

    _project_link.save(tmp_path, _project_link.ProjectLink(host="127.0.0.1:1", slug="s", workspace="w-cwd"))
    monkeypatch.chdir(tmp_path)
    captured = {}

    def fake_list_projects(host, token, *, workspace=None):
        captured["workspace"] = workspace
        return []

    monkeypatch.setattr(cli_module, "list_projects", fake_list_projects)

    result = runner.invoke(app, ["projects"])

    assert result.exit_code == 0, result.output
    assert captured["workspace"] == "w-cwd"


DEFAULT_WORKSPACE_ID = "11111111-1111-1111-1111-111111111111"


def test_resolve_workspace_priority_override_then_link_then_default(tmp_path, monkeypatch):
    """--workspace > the directory's linked workspace > the stored default."""
    import foro.cli as cli_module
    from foro.auth import WorkspaceRef

    creds = _config.Credentials(token="tok", workspace=DEFAULT_WORKSPACE_ID)

    assert cli_module._resolve_workspace("foro.sh", creds, tmp_path) == DEFAULT_WORKSPACE_ID

    _project_link.save(tmp_path, _project_link.ProjectLink(host="foro.sh", slug="s", workspace="w-link"))
    assert cli_module._resolve_workspace("foro.sh", creds, tmp_path) == "w-link"

    monkeypatch.setattr(
        cli_module, "list_workspaces", lambda host, token: [WorkspaceRef(id="w-override", name="override")]
    )
    cli_module._workspace_override = "override"
    try:
        assert cli_module._resolve_workspace("foro.sh", creds, tmp_path) == "w-override"
    finally:
        cli_module._workspace_override = None


def test_resolve_workspace_with_no_path_at_all_only_applies_the_default(tmp_path):
    """No directory to consult (e.g. a command with no `path` argument of
    its own) means only `--workspace`/the stored default can apply."""
    import foro.cli as cli_module

    creds = _config.Credentials(token="tok", workspace=DEFAULT_WORKSPACE_ID)
    _project_link.save(tmp_path, _project_link.ProjectLink(host="foro.sh", slug="s", workspace="w-link"))

    assert cli_module._resolve_workspace("foro.sh", creds) == DEFAULT_WORKSPACE_ID


def test_resolve_workspace_ignores_a_pre_129_name_shaped_default(tmp_path):
    """A hosts.yml written by the pre-#129 CLI stores a workspace *name* here,
    not an id - it must not be sent as the header (see `_is_workspace_id`)."""
    import foro.cli as cli_module

    creds = _config.Credentials(token="tok", workspace="acme")

    assert cli_module._resolve_workspace("foro.sh", creds, tmp_path) is None


def test_resolve_workspace_slug_mismatch_falls_through_to_the_default(tmp_path):
    """A `slug` that differs from the directory's own link means the link
    belongs to a different project - the stored default applies instead."""
    import foro.cli as cli_module

    creds = _config.Credentials(token="tok", workspace=DEFAULT_WORKSPACE_ID)
    _project_link.save(tmp_path, _project_link.ProjectLink(host="foro.sh", slug="linked-slug", workspace="w-link"))

    assert cli_module._resolve_workspace("foro.sh", creds, tmp_path, slug="linked-slug") == "w-link"
    assert cli_module._resolve_workspace("foro.sh", creds, tmp_path, slug="other-slug") == DEFAULT_WORKSPACE_ID
    assert cli_module._resolve_workspace("foro.sh", creds, tmp_path) == "w-link"


def test_empty_workspace_flag_is_rejected_loudly(logged_in):
    """A truthiness check would silently ignore `--workspace ""` (e.g. an
    unset shell variable) instead of failing loudly."""
    result = runner.invoke(app, ["--workspace", "", "projects"])

    assert result.exit_code == 1
    assert "cannot be empty" in result.output


def test_resolve_ignores_the_directorys_link_when_project_is_overridden(tmp_path, monkeypatch):
    """--project may name a slug this directory isn't linked to; the
    directory's own link then belongs to a different project."""
    import foro.cli as cli_module

    _project_link.save(tmp_path, _project_link.ProjectLink(host="foro.sh", slug="old-slug", workspace="w-old"))
    monkeypatch.setattr(
        cli_module, "_require_credentials", lambda: ("foro.sh", _config.Credentials(token="tok", workspace=None))
    )

    host, token, slug, workspace = cli_module._resolve(tmp_path, "other-slug")

    assert slug == "other-slug"
    assert workspace is None


def test_deploy_ignores_the_directorys_link_when_project_is_overridden(logged_in, tmp_path, monkeypatch):
    import foro.cli as cli_module
    from foro.deploy import Started

    _project_link.save(
        tmp_path, _project_link.ProjectLink(host="127.0.0.1:1", slug="old-slug", workspace="w-old")
    )
    captured = {}

    def fake_deploy_project(path, host, token, *, slug=None, force_upload=False, force_repo=False, workspace=None, ref=None, on_step=None):
        captured["workspace"] = workspace
        return Started(slug=slug or "old-slug", deployment_id="d1", url="https://x.foro.sh", created=False)

    monkeypatch.setattr(cli_module, "deploy_project", fake_deploy_project)

    result = runner.invoke(
        app, ["deploy", str(tmp_path), "--project", "other-slug", "--detach", "--skip-check"]
    )

    assert result.exit_code == 0, result.output
    assert captured["workspace"] is None


def test_deploy_still_uses_the_links_workspace_when_project_matches_it(logged_in, tmp_path, monkeypatch):
    """--project repeating the directory's own linked slug is not a mismatch."""
    import foro.cli as cli_module
    from foro.deploy import Started

    _project_link.save(
        tmp_path, _project_link.ProjectLink(host="127.0.0.1:1", slug="swift-harbor-a3f2", workspace="w-link")
    )
    captured = {}

    def fake_deploy_project(path, host, token, *, slug=None, force_upload=False, force_repo=False, workspace=None, ref=None, on_step=None):
        captured["workspace"] = workspace
        return Started(slug="swift-harbor-a3f2", deployment_id="d1", url="https://x.foro.sh", created=False)

    monkeypatch.setattr(cli_module, "deploy_project", fake_deploy_project)

    result = runner.invoke(
        app, ["deploy", str(tmp_path), "--project", "swift-harbor-a3f2", "--detach", "--skip-check"]
    )

    assert result.exit_code == 0, result.output
    assert captured["workspace"] == "w-link"


def test_deploy_uses_the_directorys_linked_workspace_when_no_override_is_given(logged_in, tmp_path, monkeypatch):
    import foro.cli as cli_module
    from foro.deploy import Started

    _project_link.save(
        tmp_path, _project_link.ProjectLink(host="127.0.0.1:1", slug="swift-harbor-a3f2", workspace="w-link")
    )
    captured = {}

    def fake_deploy_project(path, host, token, *, slug=None, force_upload=False, force_repo=False, workspace=None, ref=None, on_step=None):
        captured["workspace"] = workspace
        return Started(slug="swift-harbor-a3f2", deployment_id="d1", url="https://x.foro.sh", created=False)

    monkeypatch.setattr(cli_module, "deploy_project", fake_deploy_project)

    result = runner.invoke(app, ["deploy", str(tmp_path), "--detach", "--skip-check"])

    assert result.exit_code == 0, result.output
    assert captured["workspace"] == "w-link"


def test_link_ignores_a_pre_existing_links_workspace_when_repointing(logged_in, tmp_path, monkeypatch):
    """`link` adopts a new slug for this directory; any link already there
    is for whatever project it used to track, not this one."""
    import foro.cli as cli_module

    _project_link.save(
        tmp_path, _project_link.ProjectLink(host="127.0.0.1:1", slug="old-slug", workspace="w-old")
    )
    captured = {}

    def fake_link_project(path, host, token, slug, *, workspace=None):
        captured["workspace"] = workspace
        return {"slug": slug, "url": "https://x.foro.sh"}

    monkeypatch.setattr(cli_module, "link_project", fake_link_project)

    result = runner.invoke(app, ["link", "new-slug", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert captured["workspace"] is None


def test_link_reuses_the_links_workspace_when_the_slug_is_unchanged(logged_in, tmp_path, monkeypatch):
    """Re-running `link` for the same slug is not a repoint."""
    import foro.cli as cli_module

    _project_link.save(
        tmp_path, _project_link.ProjectLink(host="127.0.0.1:1", slug="swift-harbor-a3f2", workspace="w-link")
    )
    captured = {}

    def fake_link_project(path, host, token, slug, *, workspace=None):
        captured["workspace"] = workspace
        return {"slug": slug, "url": "https://x.foro.sh"}

    monkeypatch.setattr(cli_module, "link_project", fake_link_project)

    result = runner.invoke(app, ["link", "swift-harbor-a3f2", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert captured["workspace"] == "w-link"


def test_workspace_required_is_explained_as_ambiguity_with_several_workspaces(monkeypatch):
    import foro.cli as cli_module
    from foro.auth import WorkspaceRef

    monkeypatch.setattr(
        cli_module,
        "list_workspaces",
        lambda host, token: [WorkspaceRef(id="w-1", name="a"), WorkspaceRef(id="w-2", name="b")],
    )

    assert "more than one workspace" in cli_module._explain_workspace_required("foro.sh", "tok")


def test_workspace_required_is_explained_as_onboarding_with_no_workspaces(monkeypatch):
    import foro.cli as cli_module

    monkeypatch.setattr(cli_module, "list_workspaces", lambda host, token: [])

    assert "finish onboarding" in cli_module._explain_workspace_required("foro.sh", "tok")


def test_fail_disambiguates_workspace_required_when_host_and_token_are_given(monkeypatch, capsys):
    import foro.cli as cli_module
    from foro.auth import WorkspaceRef

    monkeypatch.setattr(
        cli_module,
        "list_workspaces",
        lambda host, token: [WorkspaceRef(id="w-1", name="a"), WorkspaceRef(id="w-2", name="b")],
    )
    err = ApiError(403, {"error": "workspace_required"}, "workspace_required")

    cli_module._fail(err, "list projects", "foro.sh", "tok")

    assert "more than one workspace" in capsys.readouterr().out


def test_logs_command_passes_the_linked_directorys_workspace_through(logged_in, tmp_path, monkeypatch):
    import foro.cli as cli_module

    _project_link.save(
        tmp_path, _project_link.ProjectLink(host="127.0.0.1:1", slug="swift-harbor-a3f2", workspace="w-link")
    )
    captured = {}

    def fake_read_runtime(host, token, slug, *, workspace=None, **query):
        captured["workspace"] = workspace
        return {"lines": [{"line": "hello"}]}

    monkeypatch.setattr(cli_module, "read_runtime", fake_read_runtime)

    result = runner.invoke(app, ["logs", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert captured["workspace"] == "w-link"


def test_projects_link_persists_the_resolved_workspace(tmp_path, monkeypatch):
    from foro import projects

    monkeypatch.setattr(
        projects,
        "get_project",
        lambda host, token, slug, *, workspace=None: {"slug": slug, "url": "https://x.foro.sh"},
    )

    projects.link(tmp_path, "foro.sh", "tok", "swift-harbor-a3f2", workspace="w-1")

    assert _project_link.load(tmp_path, "foro.sh").workspace == "w-1"

def test_matrix_prints_banner_without_a_tty():
    result = runner.invoke(app, ["matrix"])

    assert result.exit_code == 0
    assert "██████" in result.stdout
