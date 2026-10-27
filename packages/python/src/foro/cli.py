from __future__ import annotations

import json
import os
import re
import socket
import sys
import threading
import uuid
import webbrowser
from datetime import datetime, timedelta, timezone
from importlib.metadata import version
from urllib.parse import quote
from pathlib import Path
from typing import Optional

import typer

from foro import _api, _config, _project_link, auth, projects
from foro._api import ApiError
from foro._archive import ArchiveError
from foro._manifest import (
    DEFAULT_PORT,
    DEFAULT_RUNTIME,
    DEFAULT_RUNTIME_VERSIONS,
    MAX_PORT,
    MIN_PORT,
    NAME_RE,
    RUNTIME_VERSIONS,
    SIDECAR_PORT,
    ManifestError,
    is_valid_repo_path,
)
from foro._mcp import DEFAULT_TIMEOUT as DEFAULT_HANDSHAKE_TIMEOUT
from foro._mcp import HandshakeError, handshake, normalize_url
from foro._python_project import DEPENDENCY_MANAGERS
from foro.auth import (
    TOKEN_PREFIX,
    TOKEN_RE,
    AuthError,
    fetch_identity,
    list_workspaces,
    poll_for_token,
    revoke,
    start_device_flow,
)
from foro.check import run_check
from foro.deploy import DeployError, Started, get_deployment, stream_build, stream_deploy
from foro.deploy import deploy as deploy_project
from foro.logs import (
    latest_deployment_id,
    read_deployment,
    read_runtime,
    stream_runtime,
    summarize,
)
from foro.projects import ProjectError, get_project, list_deployments, list_projects
from foro.projects import link as link_project
from foro.dev import DevError, InspectorUnavailable, run_dev, start_inspector, stop
from foro._proc import MissingToolError
from foro.init import (
    GitInitError,
    ManifestFields,
    ScaffoldError,
    detect_entrypoint_candidates,
    detect_existing_dependency_manager,
    existing_foro_table_diff,
    init_git_repo,
    scaffold_new,
    MissingPyprojectError,
    write_foro_table,
)

app = typer.Typer(
    name="foro",
    help="Scaffold, validate, and run MCP servers for foro.sh.",
    no_args_is_help=True,
)


def _version_callback(show: bool) -> None:
    if show:
        typer.echo(version("foro"))
        raise typer.Exit()


_workspace_override: str | None = None


@app.callback()
def main(
    show_version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the foro CLI version and exit.",
    ),
    workspace: Optional[str] = typer.Option(
        None,
        "--workspace",
        help="Workspace (name or id) to act on, overriding the default. A root "
        "option: it goes before the subcommand, e.g. `foro --workspace acme deploy`.",
    ),
) -> None:
    """foro - the foro.sh Python SDK and CLI."""
    global _workspace_override
    _workspace_override = workspace


@app.command()
def check(
    path: Path = typer.Argument(
        Path("."), help="Repo directory to validate (default: current directory)."
    ),
) -> None:
    """Validate a project against foro.sh's deploy contract."""
    result = run_check(path)

    for warning in result.warnings:
        typer.secho(f"warning: {warning}", fg=typer.colors.YELLOW)

    if not result.ok:
        typer.secho(f"✗ {result.message} [{result.reason}]", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    typer.secho("✓ would pass foro.sh's deploy checks", fg=typer.colors.GREEN)


def _sanitize_name(raw: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", raw.lower()).strip("-")
    return slug[:48] or "my-server"


_assume_yes = False


def _prompt(*args, default, **kwargs):
    return default if _assume_yes else typer.prompt(*args, default=default, **kwargs)


def _confirm(text: str, *, default: bool) -> bool:
    return default if _assume_yes else typer.confirm(text, default=default)


def _prompt_name(default: str) -> str:
    while True:
        value = _prompt("Project name", default=default)
        if NAME_RE.match(value):
            return value
        typer.secho(f"Name must match {NAME_RE.pattern}", fg=typer.colors.RED)


def _prompt_entrypoint(default: str) -> str:
    while True:
        value = _prompt("Entrypoint", default=default)
        if value.endswith(".py") and is_valid_repo_path(value):
            return value
        typer.secho(
            "Entrypoint must be a relative .py path within the project "
            "(no `..` traversal or shell metacharacters)",
            fg=typer.colors.RED,
        )


def _prompt_runtime_version(runtime: str, default: str) -> str:
    versions = RUNTIME_VERSIONS[runtime]
    while True:
        value = _prompt(f"{runtime.capitalize()} version ({'/'.join(versions)})", default=default)
        if value in versions:
            return value
        typer.secho(f"Must be one of {', '.join(versions)}", fg=typer.colors.RED)


def _prompt_dependency_manager(default: str) -> str:
    while True:
        value = _prompt("Dependency manager", default=default)
        if value in DEPENDENCY_MANAGERS:
            return value
        typer.secho(f"Must be one of {', '.join(DEPENDENCY_MANAGERS)}", fg=typer.colors.RED)


def _prompt_port(default: int) -> int:
    while True:
        value = _prompt("Port", default=default, type=int)
        if MIN_PORT <= value <= MAX_PORT and value != SIDECAR_PORT:
            return value
        typer.secho(
            f"Port must be between {MIN_PORT} and {MAX_PORT} (excluding {SIDECAR_PORT}, "
            "reserved for the platform's health sidecar)",
            fg=typer.colors.RED,
        )


@app.command()
def init(
    name: Optional[str] = typer.Argument(
        None,
        help="Directory to scaffold a new project into. Omit to record the "
        "current directory\'s foro settings in its pyproject.toml instead.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Accept every default instead of prompting, so init runs "
        "unattended (in CI, or when an agent drives it). An existing "
        "[tool.foro] table is still never overwritten.",
    ),
) -> None:
    """Scaffold a new MCP server, or record an existing one\'s foro settings."""
    global _assume_yes
    _assume_yes = yes

    if name is not None:
        _init_from_scratch(Path(name))
    else:
        _init_existing(Path("."))


def _init_from_scratch(target: Path) -> None:
    if target.exists() and any(target.iterdir()):
        typer.secho(
            f"✗ {target} already exists and is not empty - run `foro init` with no "
            "argument inside it to configure the project that is already there",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    name = _prompt_name(_sanitize_name(target.name))
    runtime_version = _prompt_runtime_version(DEFAULT_RUNTIME, DEFAULT_RUNTIME_VERSIONS[DEFAULT_RUNTIME])
    port = _prompt_port(DEFAULT_PORT)
    git_init = _confirm("Initialize a git repo here?", default=True)

    fields = ManifestFields(name=name, entrypoint="server.py", runtime_version=runtime_version, port=port)
    try:
        scaffold_new(target, fields, git_init=git_init)
    except ScaffoldError as err:
        typer.secho(f"✗ {err}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from None
    except GitInitError as err:
        typer.secho(f"warning: {err}", fg=typer.colors.YELLOW)

    typer.secho(f"✓ scaffolded {target}", fg=typer.colors.GREEN)
    typer.echo(f"  cd {target} && foro dev")


def _init_existing(dir_path: Path) -> None:
    if not (dir_path / "pyproject.toml").is_file():
        typer.secho(
            f"✗ no pyproject.toml in {dir_path.resolve()} - run `uv init` first to configure an "
            "existing project, or `foro init <dir>` to scaffold a new one",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    candidates = detect_entrypoint_candidates(dir_path)
    if len(candidates) > 1:
        typer.echo("Multiple candidate entrypoints found: " + ", ".join(candidates))
    entrypoint_default = candidates[0] if candidates else "server.py"
    entrypoint = _prompt_entrypoint(entrypoint_default)

    detected_manager = detect_existing_dependency_manager(dir_path)
    dependency_manager = _prompt_dependency_manager(detected_manager or "uv")

    name = _prompt_name(_sanitize_name(dir_path.resolve().name))
    runtime_version = _prompt_runtime_version(DEFAULT_RUNTIME, DEFAULT_RUNTIME_VERSIONS[DEFAULT_RUNTIME])
    port = _prompt_port(DEFAULT_PORT)

    fields = ManifestFields(
        name=name,
        entrypoint=entrypoint,
        runtime_version=runtime_version,
        port=port,
        dependency_manager=dependency_manager if dependency_manager != detected_manager else None,
    )

    diff = existing_foro_table_diff(dir_path, fields)
    if diff:
        typer.echo("pyproject.toml already has a [tool.foro] table. Diff:")
        typer.echo(diff)
        if not _confirm("Overwrite?", default=False):
            typer.echo("Aborted.")
            raise typer.Exit(code=1)

    try:
        wrote = write_foro_table(dir_path, fields)
    except MissingPyprojectError as err:
        typer.secho(f"✗ {err}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from None

    if wrote:
        typer.secho(f"✓ updated {dir_path / 'pyproject.toml'}", fg=typer.colors.GREEN)
    else:
        typer.secho("✓ nothing to configure - this project deploys as it is", fg=typer.colors.GREEN)

    if not (dir_path / ".git").exists() and _confirm("Initialize a git repo here?", default=True):
        try:
            init_git_repo(dir_path)
        except GitInitError as err:
            typer.secho(f"warning: {err}", fg=typer.colors.YELLOW)


@app.command()
def dev(
    path: Path = typer.Argument(Path("."), help="Repo directory to run (default: current directory)."),
    once: bool = typer.Option(
        False,
        "--once",
        help="Verify and exit instead of leaving the server running - the form "
        "to use when a script or a coding agent drives it.",
    ),
    inspect: bool = typer.Option(
        True,
        "--inspect/--no-inspect",
        help="Open the MCP Inspector against the running server (needs Node.js). Never runs with --once.",
    ),
) -> None:
    """Run the server locally the way foro.sh will."""
    try:
        process, result = run_dev(path)
    except ManifestError as err:
        typer.secho(f"✗ {err} [{err.reason}]", fg=typer.colors.RED)
        raise typer.Exit(code=1) from None
    except (DevError, MissingToolError) as err:
        typer.secho(f"✗ {err}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from None

    typer.secho(f"✓ would pass foro.sh's health check (port {result.port})", fg=typer.colors.GREEN)
    typer.echo("Tools: " + (", ".join(result.tool_names) if result.tool_names else "(none)"))

    if once:
        stop(process)
        return

    inspector = None
    if inspect:
        try:
            inspector = start_inspector(result.port)
        except (MissingToolError, InspectorUnavailable) as err:
            typer.secho(f"warning: no inspector - {err}", fg=typer.colors.YELLOW)

    typer.echo("Press Ctrl+C to stop.")
    try:
        process.wait()
    except KeyboardInterrupt:
        pass
    finally:
        stop(process)
        if inspector is not None:
            stop(inspector)


@app.command()
def verify(
    url: str = typer.Argument(..., help="Deployed server URL, e.g. https://<slug>.foro.sh"),
    timeout: float = typer.Option(
        DEFAULT_HANDSHAKE_TIMEOUT, "--timeout", help="Seconds to wait for a response."
    ),
) -> None:
    """Prove a deployed server actually serves MCP, not just that it responds."""
    target = normalize_url(url)
    try:
        tool_names = handshake(target, timeout)
    except HandshakeError as err:
        typer.secho(f"✗ {err}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from None

    typer.secho(f"✓ {target} is serving MCP", fg=typer.colors.GREEN)
    typer.echo("Tools: " + (", ".join(tool_names) if tool_names else "(none)"))


auth_app = typer.Typer(no_args_is_help=True, help="Sign in to foro.sh so the CLI can act on your behalf.")
app.add_typer(auth_app, name="auth")


def _require_credentials() -> tuple[str, _config.Credentials]:
    host = _config.resolve_host()
    creds = _config.load(host)
    if creds is None:
        typer.secho(f"✗ not logged in to {host} - run `foro auth login`", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    if _config.has_insecure_permissions() and not creds.from_env:
        typer.secho(
            f"warning: {_config.config_path()} is readable by other users - `chmod 600` it",
            fg=typer.colors.YELLOW,
        )
    return host, creds


def _resolve_workspace_ref(host: str, token: str, query: str) -> auth.WorkspaceRef:
    try:
        workspaces = list_workspaces(host, token)
    except ApiError as err:
        raise _fail(err, "list workspaces") from None

    matches = [w for w in workspaces if query in (w.id, w.name)]
    if not matches:
        typer.secho(f"✗ no workspace matches {query!r} - run `foro workspace list`", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    if len(matches) > 1:
        typer.secho(f"✗ more than one workspace matches {query!r} - use its id instead", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    return matches[0]


def _is_workspace_id(value: str | None) -> bool:
    """Workspace ids are server-generated UUIDs. A pre-#129 CLI stored the
    workspace *name* in this same field, so a stale `hosts.yml` entry must
    not be sent as a header - it would 403 as bare "Forbidden" for every
    command instead of just falling back to the server's own resolution."""
    if not value:
        return False
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def _resolve_workspace(
    host: str, creds: _config.Credentials, path: Path | None = None, *, slug: str | None = None
) -> str | None:
    """`path` is the directory whose own link to consult, if any. `slug` is
    the project actually being acted on - when given, the link only counts
    if it names that same project, so a slug this directory isn't linked to
    (via `--project`, or `link` adopting a different one) never inherits a
    stale link's workspace. Omit `slug` to trust the link unconditionally."""
    if _workspace_override is not None:
        if not _workspace_override:
            typer.secho("✗ --workspace cannot be empty", fg=typer.colors.RED)
            raise typer.Exit(code=1)
        return _resolve_workspace_ref(host, creds.token, _workspace_override).id
    if path is not None:
        link = _project_link.load(path, host)
        if link and link.workspace and (slug is None or link.slug == slug):
            return link.workspace
    return creds.workspace if _is_workspace_id(creds.workspace) else None


def _select_default_workspace(identity: auth.Identity, *, interactive: bool) -> auth.WorkspaceRef | None:
    if identity.workspace is not None:
        return identity.workspace
    if len(identity.workspaces) == 1:
        return identity.workspaces[0]
    if not interactive or not identity.workspaces:
        return None

    typer.echo("You belong to more than one workspace:")
    for i, ref in enumerate(identity.workspaces, start=1):
        typer.echo(f"  {i}. {ref.name}")
    choice = typer.prompt("Pick a default workspace", type=int, default=1)
    index = choice - 1
    if not (0 <= index < len(identity.workspaces)):
        typer.secho(
            "✗ invalid choice - default workspace left unchanged; run `foro workspace use` to set one",
            fg=typer.colors.YELLOW,
        )
        return None
    return identity.workspaces[index]


@auth_app.command("login")
def auth_login(
    with_token: bool = typer.Option(
        False,
        "--with-token",
        help="Read a token from stdin instead of running the device flow, for CI. "
        "Implies --force: stdin is the token, so there is nothing left to answer "
        "a confirmation prompt with.",
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Replace an existing login without asking."),
) -> None:
    """Authenticate with foro.sh."""
    host = _config.resolve_host()

    if os.environ.get(_config.ENV_TOKEN):
        typer.secho(
            f"✗ {_config.ENV_TOKEN} is set, which overrides any stored login - unset it first",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    token = _read_token_from_stdin() if with_token else None

    existing = _config.load(host)
    if existing and not force and not with_token:
        who = f" as {existing.user}" if existing.user else ""
        if not typer.confirm(f"Already logged in to {host}{who}. Log in again?", default=False):
            raise typer.Exit(code=1)

    if token is None:
        token = _run_device_flow(host)

    try:
        identity = fetch_identity(host, token)
    except ApiError as err:
        typer.secho(f"✗ the token was rejected by {host}: {err}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from None

    default_workspace = _select_default_workspace(identity, interactive=not with_token)
    if default_workspace is None and existing and existing.workspace:
        # Non-interactive re-login (or a mistyped prompt) resolved nothing new -
        # keep whatever default was already working rather than wiping it.
        default_workspace = next((w for w in identity.workspaces if w.id == existing.workspace), None)
    _config.save(
        host,
        _config.Credentials(
            token=token,
            user=identity.user,
            workspace=default_workspace.id if default_workspace else None,
        ),
    )
    workspace = f" (workspace: {default_workspace.name})" if default_workspace else ""
    typer.secho(f"✓ Logged in as {identity.user}{workspace}", fg=typer.colors.GREEN)


def _read_token_from_stdin() -> str:
    token = sys.stdin.read().strip()
    if not token:
        typer.secho("✗ no token on stdin", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    if not TOKEN_RE.match(token):
        typer.secho(
            f"✗ that is not a foro token - expected {TOKEN_PREFIX} followed by 43 characters",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)
    return token


def _open_browser(url: str) -> None:
    try:
        webbrowser.open(url)
    except Exception:
        pass


def _run_device_flow(host: str) -> str:
    try:
        grant = start_device_flow(host, label=socket.gethostname())
    except ApiError as err:
        typer.secho(f"✗ {err}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from None

    typer.secho(f"! First copy your one-time code: {grant.user_code}", fg=typer.colors.YELLOW)
    interactive = sys.stdin.isatty()
    if interactive:
        typer.echo(
            f"Press Enter to open {host} in your browser... "
            f"(or paste {grant.verification_uri_complete})"
        )
    else:
        typer.echo(f"Open this to authorize: {grant.verification_uri_complete}")
    try:
        if interactive:
            try:
                input()
            except EOFError:
                typer.echo("")
            _open_browser(grant.verification_uri_complete)

        def tick(elapsed: float) -> None:
            if sys.stdout.isatty():
                typer.echo(f"\r- Waiting for authorization... {int(elapsed)}s", nl=False)

        payload = poll_for_token(host, grant, on_wait=tick)
    except KeyboardInterrupt:
        typer.echo("")
        raise typer.Exit(code=1) from None
    except AuthError as err:
        typer.echo("")
        typer.secho(f"✗ {err}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from None
    except ApiError as err:
        typer.echo("")
        typer.secho(f"✗ {err}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from None

    typer.echo("")
    return payload["access_token"]


@auth_app.command("status")
def auth_status() -> None:
    """Show who you are logged in as, and prove the token still works."""
    host, creds = _require_credentials()

    try:
        identity = fetch_identity(host, creds.token)
    except ApiError as err:
        typer.secho(f"✗ the stored token is no longer valid ({err})", fg=typer.colors.RED)
        typer.echo("  Run `foro auth login` to get a new one.")
        raise typer.Exit(code=1) from None

    where = f"${_config.ENV_TOKEN}" if creds.from_env else str(_config.config_path())
    typer.echo(host)
    typer.secho(f"  ✓ Logged in as {identity.user}", fg=typer.colors.GREEN)
    if creds.workspace:
        default_ref = next((w for w in identity.workspaces if w.id == creds.workspace), None)
        name = default_ref.name if default_ref else f"{creds.workspace} (not found - run `foro workspace use`)"
        typer.echo(f"    Workspace: {name}")
    typer.echo(f"    Token: {creds.token[: len(TOKEN_PREFIX) + 8]}… ({where})")


@auth_app.command("logout")
def auth_logout() -> None:
    """Revoke this machine's token and forget it."""
    host, creds = _require_credentials()

    if creds.from_env:
        typer.secho(
            f"✗ the token comes from ${_config.ENV_TOKEN}, so there is nothing stored to log out of",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    who = f" as {creds.user}" if creds.user else ""
    if not typer.confirm(f"Log out of {host}{who}?", default=True):
        raise typer.Exit(code=1)

    try:
        revoke(host, creds.token)
        typer.secho("✓ Logged out; token revoked", fg=typer.colors.GREEN)
    except (ApiError, AuthError) as err:
        typer.secho(f"warning: could not revoke server-side ({err})", fg=typer.colors.YELLOW)
        typer.secho("✓ Logged out locally; revoke it on /account", fg=typer.colors.GREEN)

    _config.delete(host)


@auth_app.command("token")
def auth_token() -> None:
    """Print the raw token, for `curl -H "Authorization: Bearer $(foro auth token)"`."""
    _, creds = _require_credentials()
    typer.echo(creds.token)


workspace_app = typer.Typer(no_args_is_help=True, help="See and switch which workspace the CLI acts on.")
app.add_typer(workspace_app, name="workspace")


@workspace_app.command("list")
def workspace_list() -> None:
    """List every workspace you belong to; `*` marks the current default."""
    host, creds = _require_credentials()
    try:
        workspaces = list_workspaces(host, creds.token)
    except ApiError as err:
        raise _fail(err, "list workspaces") from None

    if not workspaces:
        typer.echo("no workspaces yet - finish onboarding in the dashboard")
        return
    for workspace in workspaces:
        marker = "*" if workspace.id == creds.workspace else " "
        typer.echo(f"{marker} {workspace.name:<28} {workspace.id}")


@workspace_app.command("use")
def workspace_use(
    query: str = typer.Argument(..., help="Workspace name or id to make the default."),
) -> None:
    """Make a workspace the CLI's default for commands with no --workspace."""
    host, creds = _require_credentials()
    if creds.from_env:
        typer.secho(
            f"✗ the token comes from ${_config.ENV_TOKEN}, so there is no stored login "
            "to set a default workspace on - pass --workspace instead",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    ref = _resolve_workspace_ref(host, creds.token, query)
    _config.save(host, _config.Credentials(token=creds.token, user=creds.user, workspace=ref.id))
    typer.secho(f"✓ default workspace set to {ref.name}", fg=typer.colors.GREEN)


def _explain_workspace_required(host: str, token: str) -> str:
    try:
        workspaces = list_workspaces(host, token)
    except (ApiError, AuthError):
        workspaces = []
    if len(workspaces) > 1:
        return (
            "your account belongs to more than one workspace - "
            "run `foro workspace use` to pick a default, or pass --workspace"
        )
    return "finish onboarding in the dashboard first - your account has no workspace yet"


def _fail(err: ApiError, action: str, host: str | None = None, token: str | None = None) -> typer.Exit:
    message = _api.explain(err, action=action)
    if err.code == "workspace_required" and host and token:
        message = _explain_workspace_required(host, token)
    typer.secho(f"✗ {message}", fg=typer.colors.RED)
    return typer.Exit(code=1)


def _resolve(path: Path, project: str | None) -> tuple[str, str, str, str | None]:
    host, creds = _require_credentials()
    try:
        slug = projects.resolve_slug(path, host, project)
    except ProjectError as err:
        typer.secho(f"✗ {err}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from None
    return host, creds.token, slug, _resolve_workspace(host, creds, path, slug=slug)


@app.command()
def deploy(
    path: Path = typer.Argument(Path("."), help="Repo directory to deploy (default: current)."),
    project: Optional[str] = typer.Option(None, "--project", help="Deploy to this slug."),
    upload: bool = typer.Option(False, "--upload", help="Force uploading the working tree."),
    repo: bool = typer.Option(False, "--repo", help="Force building from the linked repo branch."),
    ref: Optional[str] = typer.Option(
        None, "--ref", help="Build this branch or tag instead of the configured branch."
    ),
    detach: bool = typer.Option(False, "--detach", "-d", help="Don't stream; print the URL and exit."),
    skip_check: bool = typer.Option(False, "--skip-check", help="Deploy without running foro check."),
) -> None:
    """Deploy this directory to foro.sh and stream the build."""
    if upload and repo:
        typer.secho("✗ --upload and --repo are mutually exclusive", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    host, creds = _require_credentials()
    workspace = _resolve_workspace(host, creds, path, slug=project)

    if not skip_check and not repo:
        result = run_check(path)
        if not result.ok:
            typer.secho(f"✗ {result.message} [{result.reason}]", fg=typer.colors.RED)
            raise typer.Exit(code=1)

    try:
        started = deploy_project(
            path,
            host,
            creds.token,
            slug=project,
            force_upload=upload,
            force_repo=repo,
            workspace=workspace,
            ref=ref,
            on_step=lambda message: typer.echo(f"- {message}"),
        )
    except (DeployError, ArchiveError) as err:
        typer.secho(f"✗ {err}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from None
    except ApiError as err:
        raise _fail(err, "deploy", host, creds.token) from None

    if started.created:
        typer.echo(f"- created {started.slug}")
        _offer_gitignore(path)

    typer.echo(f"- deploying {started.slug} ({started.deployment_id[:8]})")
    if detach:
        typer.echo(f"  {normalize_url(started.url)}")
        return

    _stream_deploy(host, creds.token, started, workspace)


def _offer_gitignore(repo_dir: Path) -> None:
    if _project_link.is_gitignored(repo_dir):
        return
    if not sys.stdin.isatty():
        typer.echo(f"  add {_project_link.GITIGNORE_ENTRY} to .gitignore - the link is per-clone")
        return
    if typer.confirm(f"Add {_project_link.GITIGNORE_ENTRY} to .gitignore?", default=True):
        _project_link.add_to_gitignore(repo_dir)


def _stream_deploy(host: str, token: str, started, workspace: str | None = None) -> None:
    build_lines: list[str] = []

    def pump_build() -> None:
        try:
            for entry in stream_build(host, token, started.slug, started.deployment_id, workspace=workspace):
                line = entry.get("line", "")
                build_lines.append(line)
                typer.secho(f"  │ {line}", dim=True)
        except ApiError:
            pass

    pump = threading.Thread(target=pump_build, daemon=True)
    pump.start()

    try:
        for entry in stream_deploy(host, token, started.slug, started.deployment_id, workspace=workspace):
            typer.echo(entry.get("line", ""))
    except KeyboardInterrupt:
        typer.echo("")
        typer.secho(
            f"detached - the deploy is still running. `foro logs --deploy --deployment {started.deployment_id}` to read it.",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(code=0) from None
    except ApiError as err:
        raise _fail(err, "stream the deploy", host, token) from None

    pump.join(timeout=2)

    try:
        final = get_deployment(host, token, started.slug, started.deployment_id, workspace=workspace)
    except ApiError as err:
        raise _fail(err, "read the deployment", host, token) from None

    if final["status"] == "live":
        typer.secho(f"✓ live at {normalize_url(started.url)}", fg=typer.colors.GREEN)
        return

    typer.secho(f"✗ deploy {final['status']}", fg=typer.colors.RED)
    if final.get("error_message"):
        typer.echo(f"  {final['error_message']}")
    if final.get("reason"):
        typer.echo(f"  reason: {final['reason']}")
    raise typer.Exit(code=1)


@app.command()
def logs(
    path: Path = typer.Argument(Path("."), help="Linked repo directory (default: current)."),
    project: Optional[str] = typer.Option(None, "--project", help="Read this slug's logs."),
    follow: bool = typer.Option(False, "--follow", "-f", help="Stream live runtime logs."),
    deploy_log: bool = typer.Option(False, "--deploy", help="Read a deployment's deploy log."),
    build_log: bool = typer.Option(False, "--build", help="Read a deployment's build log."),
    deployment: Optional[str] = typer.Option(
        None, "--deployment", help="Which deployment (default: the most recent)."
    ),
    minutes: Optional[int] = typer.Option(
        None, "--minutes", min=1, help="Read this many minutes back from --until."
    ),
    until: Optional[datetime] = typer.Option(
        None, "--until", help="End of the window (ISO-8601, default: now)."
    ),
    contains: Optional[str] = typer.Option(
        None, "--contains", help="Keep only lines containing this text (case-insensitive)."
    ),
    summary: bool = typer.Option(
        False, "--summary", help="Digest the window: totals, error hours, recurring messages."
    ),
    hours: int = typer.Option(24, "--hours", min=1, max=720, help="--summary window."),
    as_json: bool = typer.Option(False, "--json", help="One JSON object per line, for jq."),
) -> None:
    """Show a project's runtime logs, or one deployment's deploy/build log."""
    if sum([deploy_log, build_log, follow, summary]) > 1:
        typer.secho(
            "✗ --deploy, --build, --follow and --summary are mutually exclusive",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    host, token, slug, workspace = _resolve(path, project)

    def emit(entry: dict) -> None:
        typer.echo(json.dumps(entry) if as_json else entry.get("line", ""))

    try:
        if deploy_log or build_log:
            deployment_id = deployment or latest_deployment_id(host, token, slug, workspace=workspace)
            if not deployment_id:
                typer.secho(f"✗ {slug} has no deployments yet", fg=typer.colors.RED)
                raise typer.Exit(code=1)
            kind = "build" if build_log else "deploy"
            for entry in read_deployment(host, token, slug, deployment_id, kind, workspace=workspace):
                emit(entry)
            return

        if follow:
            try:
                for entry in stream_runtime(host, token, slug, workspace=workspace):
                    emit(entry)
            except KeyboardInterrupt:
                typer.echo("")
            return

        if summary:
            since = datetime.now(timezone.utc) - timedelta(hours=hours)
            payload = summarize(host, token, slug, since.isoformat(), workspace=workspace)
            _print_summary(payload, as_json)
            return

        query = {}
        if minutes or until:
            end = until or datetime.now(timezone.utc)
            if end.tzinfo is None:
                end = end.astimezone()
            query = {
                "from": (end - timedelta(minutes=minutes or 60)).isoformat(),
                "to": end.isoformat(),
            }
        if contains:
            # One quoted phrase, as the dashboard search sends it.
            query["q"] = '"' + contains.replace("\\", "\\\\").replace('"', '\\"') + '"'
        payload = read_runtime(host, token, slug, workspace=workspace, **query)
        lines = payload.get("lines", [])
        if not lines and query:
            typer.echo("no matching lines")
            return
        if not lines:
            typer.echo(
                "no stored logs - retention is plan-gated (24h on Free), so this is "
                "normal for a quiet or recently deployed server"
            )
            return
        for entry in lines:
            emit(entry)
        if payload.get("complete") is False and not as_json:
            typer.secho(
                f"only the newest lines were kept (back to {payload.get('scanned_from')}) - "
                "narrow --contains or --minutes to see older ones",
                fg=typer.colors.YELLOW,
            )
    except ApiError as err:
        raise _fail(err, "read logs", host, token) from None


def _print_summary(s: dict, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(s))
        return
    typer.echo(
        f"{s['from']} to {s['to']}: {s['lines']} lines, {s['errors']} errors, "
        f"{s['warnings']} warnings"
    )
    peaks = sorted((h for h in s["hours"] if h["errors"]), key=lambda h: -h["errors"])[:3]
    if peaks:
        typer.echo("busiest error hours: " + ", ".join(f"{h['hour']} ({h['errors']})" for h in peaks))
    for g in s["groups"]:
        typer.echo(f"\n{g['level']} x{g['count']}, {g['first_seen']} to {g['last_seen']}")
        typer.echo(f"  {g['signature']}")
        if g.get("examples"):
            for line in g["examples"][0].splitlines()[:8]:
                typer.secho(f"    {line}", dim=True)
    if s.get("groups_omitted"):
        typer.echo(f"\n{s['groups_omitted']} rarer messages not shown")


# Bare `foro projects` lists; do not set no_args_is_help.
projects_app = typer.Typer(help="Inspect your foro.sh projects.")
app.add_typer(projects_app, name="projects")


@projects_app.callback(invoke_without_command=True)
def projects_default(ctx: typer.Context) -> None:
    """List every project in the resolved workspace (the current directory's
    linked workspace, if any, ahead of the default)."""
    if ctx.invoked_subcommand is not None:
        return
    host, creds = _require_credentials()
    workspace = _resolve_workspace(host, creds, Path("."))
    try:
        rows = list_projects(host, creds.token, workspace=workspace)
    except ApiError as err:
        raise _fail(err, "list projects", host, creds.token) from None

    if not rows:
        typer.echo("no projects yet - `foro deploy` creates one from this directory")
        return
    for row in rows:
        status = "building" if row.get("building") else row["status"]
        typer.echo(f"{row['slug']:<28} {status:<10} {row['url']}")


@projects_app.command("show")
def projects_show(
    path: Path = typer.Argument(Path("."), help="Linked repo directory (default: current)."),
    project: Optional[str] = typer.Option(None, "--project", help="Show this slug."),
) -> None:
    """Show one project, defaulting to the one this directory is linked to."""
    host, token, slug, workspace = _resolve(path, project)
    try:
        row = get_project(host, token, slug, workspace=workspace)
        history = list_deployments(host, token, slug, workspace=workspace)
    except ApiError as err:
        raise _fail(err, "read the project", host, token) from None

    typer.echo(row["slug"])
    typer.echo(f"  Name:    {row.get('name') or '(none)'}")
    typer.echo(f"  Status:  {'building' if row.get('building') else row['status']}")
    typer.echo(f"  Source:  {row['source']}")
    if row.get("repo_owner"):
        typer.echo(f"  Repo:    {row['repo_owner']}/{row['repo_name']}@{row['repo_branch']}")
        typer.echo(f"  Auto-deploy: {'on' if row.get('auto_deploy') else 'off'}")
    typer.echo(f"  URL:     {normalize_url(row['url'])}")
    typer.echo(f"  Auth:    {row.get('auth_mode')}")
    if history:
        last = history[0]
        typer.echo(f"  Last deploy: {last['status']} at {last['created_at']} ({last['id'][:8]})")


@app.command()
def link(
    slug: str = typer.Argument(..., help="Slug of an existing project to adopt."),
    path: Path = typer.Argument(Path("."), help="Directory to link (default: current)."),
) -> None:
    """Point this directory at a project created in the dashboard."""
    host, creds = _require_credentials()
    workspace = _resolve_workspace(host, creds, path, slug=slug)
    try:
        row = link_project(path, host, creds.token, slug, workspace=workspace)
    except ApiError as err:
        raise _fail(err, "link the project", host, creds.token) from None

    typer.secho(f"✓ linked to {row['slug']} ({row['url']})", fg=typer.colors.GREEN)
    _offer_gitignore(path)


@app.command()
def unlink(
    path: Path = typer.Argument(Path("."), help="Directory to unlink (default: current)."),
) -> None:
    """Forget which project this directory deploys to."""
    if _project_link.delete(path):
        typer.secho("✓ unlinked", fg=typer.colors.GREEN)
        return
    typer.echo("this directory wasn't linked")


@app.command("open")
def open_project(
    path: Path = typer.Argument(Path("."), help="Linked repo directory (default: current)."),
    project: Optional[str] = typer.Option(None, "--project", help="Open this slug."),
) -> None:
    """Open the deployed URL in a browser."""
    host, token, slug, workspace = _resolve(path, project)
    try:
        row = get_project(host, token, slug, workspace=workspace)
    except ApiError as err:
        raise _fail(err, "read the project", host, token) from None

    typer.echo(row["url"])
    webbrowser.open(row["url"])


def _call(host: str, token: str, method: str, path: str, action: str, **kwargs):
    try:
        return _api.request(method, path, host=host, token=token, **kwargs)
    except ApiError as err:
        raise _fail(err, action, host, token) from None


def _print_json(payload) -> None:
    typer.echo(json.dumps(payload, indent=2))


@app.command()
def rollback(
    deployment: str = typer.Argument(..., help="Earlier deployment to redeploy (`foro deployments`)."),
    path: Path = typer.Argument(Path("."), help="Linked repo directory (default: current)."),
    project: Optional[str] = typer.Option(None, "--project", help="Roll back this slug."),
    detach: bool = typer.Option(False, "--detach", "-d", help="Don't stream; print the URL and exit."),
) -> None:
    """Redeploy the exact commit of an earlier, successful deployment."""
    host, token, slug, workspace = _resolve(path, project)
    created = _call(
        host, token, "POST", f"/api/projects/{slug}/deployments/{quote(deployment, safe='')}/rollback",
        "roll back", workspace=workspace,
    )
    row = _call(host, token, "GET", f"/api/projects/{slug}", "read the project", workspace=workspace)
    started = Started(slug=slug, deployment_id=created["id"], url=row["url"], created=False)
    typer.echo(f"- rolling back {slug} ({started.deployment_id[:8]})")
    if detach:
        typer.echo(f"  {normalize_url(started.url)}")
        return
    _stream_deploy(host, token, started, workspace)


def _deployment_or_latest(host: str, token: str, slug: str, workspace: str | None, deployment: str | None) -> str:
    try:
        deployment = deployment or latest_deployment_id(host, token, slug, workspace=workspace)
    except ApiError as err:
        raise _fail(err, "read deployments", host, token) from None
    if not deployment:
        typer.secho(f"✗ {slug} has no deployments yet", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    return quote(deployment, safe="")


@app.command()
def cancel(
    path: Path = typer.Argument(Path("."), help="Linked repo directory (default: current)."),
    project: Optional[str] = typer.Option(None, "--project", help="Cancel this slug's deployment."),
    deployment: Optional[str] = typer.Option(
        None, "--deployment", help="Which deployment (default: the most recent)."
    ),
) -> None:
    """Stop a deployment that is still building or starting. What is live keeps serving."""
    host, token, slug, workspace = _resolve(path, project)
    deployment = _deployment_or_latest(host, token, slug, workspace, deployment)
    row = _call(
        host, token, "POST", f"/api/projects/{slug}/deployments/{deployment}/cancel", "cancel",
        workspace=workspace,
    )
    typer.echo(f"deployment {row['id'][:8]} is {row['status']}")


# Bare `foro deployments` lists; do not set no_args_is_help.
deployments_app = typer.Typer(help="Inspect a project's deployments.")
app.add_typer(deployments_app, name="deployments")


@deployments_app.callback(invoke_without_command=True)
def deployments_default(
    ctx: typer.Context,
    path: Path = typer.Option(Path("."), "--path", help="Linked repo directory (default: current)."),
    project: Optional[str] = typer.Option(None, "--project", help="List this slug's deployments."),
    limit: int = typer.Option(10, "--limit", min=1, help="How many, newest first."),
    as_json: bool = typer.Option(False, "--json", help="Print the API response."),
) -> None:
    """List recent deployments, newest first."""
    if ctx.invoked_subcommand is not None:
        return
    host, token, slug, workspace = _resolve(path, project)
    try:
        rows = list_deployments(host, token, slug, workspace=workspace)[:limit]
    except ApiError as err:
        raise _fail(err, "list deployments", host, token) from None
    if as_json:
        _print_json(rows)
        return
    if not rows:
        typer.echo(f"{slug} has no deployments yet")
    for d in rows:
        sha = (d.get("git_sha") or "")[:7]
        typer.echo(f"{d['id']}  {d['status']:<10} {sha:<7}  {d['created_at']}")
        if d.get("error_message"):
            typer.secho(f"    {d['error_message'].splitlines()[0]}", dim=True)


@deployments_app.command("show")
def deployments_show(
    path: Path = typer.Argument(Path("."), help="Linked repo directory (default: current)."),
    project: Optional[str] = typer.Option(None, "--project", help="Show this slug's deployment."),
    deployment: Optional[str] = typer.Option(
        None, "--deployment", help="Which deployment (default: the most recent)."
    ),
    as_json: bool = typer.Option(False, "--json", help="Print the API response."),
) -> None:
    """One deployment's status, error and how to resolve it."""
    host, token, slug, workspace = _resolve(path, project)
    deployment = _deployment_or_latest(host, token, slug, workspace, deployment)
    row = _call(
        host, token, "GET", f"/api/projects/{slug}/deployments/{deployment}", "read the deployment",
        workspace=workspace,
    )
    if as_json:
        _print_json(row)
        return
    typer.echo(f"{row['id']}: {row['status']}")
    if row.get("git_sha"):
        typer.echo(f"  Commit:  {row['git_sha'][:12]}")
    typer.echo(f"  Created: {row['created_at']}")
    if row.get("finished_at"):
        typer.echo(f"  Done:    {row['finished_at']}")
    if row.get("error_message"):
        typer.echo(f"  Error:   {row['error_message']}")
    if row.get("reason"):
        typer.echo(f"  Reason:  {row['reason']}")
    if row.get("resolve_prompt"):
        typer.echo(f"\nTo resolve with AI, paste:\n\n{row['resolve_prompt']}")
    typer.echo(f"\n`foro logs --deploy --deployment {row['id']}` reads its log")


@projects_app.command("auto-deploy")
def projects_auto_deploy(
    state: str = typer.Argument(..., help="on or off."),
    path: Path = typer.Argument(Path("."), help="Linked repo directory (default: current)."),
    project: Optional[str] = typer.Option(None, "--project", help="Change this slug."),
) -> None:
    """Deploy on every push to the project's branch, or only on request. Repo projects only."""
    if state not in ("on", "off"):
        typer.secho("✗ state must be on or off", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    host, token, slug, workspace = _resolve(path, project)
    _call(
        host, token, "PATCH", f"/api/projects/{slug}/auto-deploy", "change auto-deploy",
        workspace=workspace, body={"auto_deploy": state == "on"},
    )
    typer.secho(f"✓ auto-deploy is {state} for {slug}", fg=typer.colors.GREEN)


@projects_app.command("create")
def projects_create(
    template: Optional[str] = typer.Option(None, "--template", help="Template id (`foro templates`)."),
    name: Optional[str] = typer.Option(None, "--name", help="Repo and project name, with --template."),
    repo: Optional[str] = typer.Option(None, "--repo", help='"owner/name" (`foro repos`).'),
    branch: Optional[str] = typer.Option(None, "--branch", help="Branch to deploy, with --repo."),
    subdir: str = typer.Option(".", "--path", help="Directory holding the manifest, with --repo."),
) -> None:
    """Create a project from a template (deploys at once) or a repo (deploy it next)."""
    if bool(template) == bool(repo):
        typer.secho("✗ pass exactly one of --template or --repo", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    if template and not (name and re.fullmatch(r"[a-z0-9-]{3,48}", name)):
        typer.secho("✗ --name: 3-48 lowercase letters, digits or dashes", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    if repo and not (branch and re.fullmatch(r"[^/\s]+/[^/\s]+", repo)):
        typer.secho('✗ --repo needs "owner/name" and --branch', fg=typer.colors.RED)
        raise typer.Exit(code=1)

    host, creds = _require_credentials()
    workspace = _resolve_workspace(host, creds)
    if template:
        row = _call(
            host, creds.token, "POST", "/api/projects/from-template", "create the project",
            workspace=workspace, body={"template_id": template, "name": name},
        )
        typer.secho(f"✓ created {row['slug']}; its first deploy is running", fg=typer.colors.GREEN)
        typer.echo(f"  `foro deployments show --project {row['slug']}` follows it")
        return
    owner, repo_name = repo.split("/")
    row = _call(
        host, creds.token, "POST", "/api/projects", "create the project",
        workspace=workspace,
        body={"repo_owner": owner, "repo_name": repo_name, "repo_branch": branch, "manifest_path": subdir},
    )
    typer.secho(f"✓ created {row['slug']} from {repo}@{branch}", fg=typer.colors.GREEN)
    typer.echo(f"  `foro link {row['slug']}` in a clone, then `foro deploy --repo`")


@app.command()
def templates(as_json: bool = typer.Option(False, "--json", help="Print the API response.")) -> None:
    """Starter servers `foro projects create --template` can copy and deploy."""
    host, creds = _require_credentials()
    rows = _call(host, creds.token, "GET", "/api/templates", "list templates")
    if as_json:
        _print_json(rows)
        return
    for t in rows:
        typer.echo(f"{t['id']:<28} {t['runtime']:<8} {t['description']}")


@app.command()
def repos(as_json: bool = typer.Option(False, "--json", help="Print the API response.")) -> None:
    """Repositories you can deploy, most recently pushed first."""
    host, creds = _require_credentials()
    rows = _call(
        host, creds.token, "GET", "/api/repos", "list repositories", workspace=_resolve_workspace(host, creds)
    )
    if as_json:
        _print_json(rows)
        return
    if not rows:
        typer.echo("no repositories found - connect a git account in the dashboard")
    for r in rows:
        typer.echo(f"{r['owner']}/{r['name']:<40} {r['default_branch']}{'  (private)' if r.get('private') else ''}")


@workspace_app.command("create")
def workspace_create(name: str = typer.Argument(..., help="Usually your team or company.")) -> None:
    """Create a workspace you own, on the Free plan, with an example server."""
    host, creds = _require_credentials()
    ws = _call(host, creds.token, "POST", "/api/workspaces", "create a workspace", body={"name": name.strip()})
    typer.secho(f"✓ created {ws['name']} ({ws['plan']} plan) - `foro workspace use {ws['id']}` to make it the default", fg=typer.colors.GREEN)


@workspace_app.command("rename")
def workspace_rename(name: str = typer.Argument(..., help="The new name.")) -> None:
    """Rename the current workspace (or the one --workspace names). Owners only."""
    host, creds = _require_credentials()
    updated = _call(
        host, creds.token, "PATCH", "/api/workspaces", "rename the workspace",
        workspace=_resolve_workspace(host, creds), body={"name": name.strip()},
    )
    typer.secho(f"✓ renamed to {updated['name']}", fg=typer.colors.GREEN)


@app.command()
def incidents(as_json: bool = typer.Option(False, "--json", help="Print the API response.")) -> None:
    """Recent alert incidents in the workspace, newest first."""
    host, creds = _require_credentials()
    rows = _call(
        host, creds.token, "GET", "/api/workspaces/alerts/incidents", "list incidents",
        workspace=_resolve_workspace(host, creds),
    )["incidents"]
    if as_json:
        _print_json(rows)
        return
    if not rows:
        typer.echo("no incidents")
    for i in rows:
        state = f"resolved {i['resolved_at']}" if i.get("resolved_at") else "still open"
        typer.echo(f"{i['project_slug']} {i['tool']} {i['trigger']}: opened {i['opened_at']}, {state}")


@app.command()
def metrics(
    path: Path = typer.Argument(Path("."), help="Linked repo directory (default: current)."),
    project: Optional[str] = typer.Option(None, "--project", help="Read this slug's metrics."),
    as_json: bool = typer.Option(False, "--json", help="Print the API response."),
) -> None:
    """Tool-call volume, error rate, p95 latency, uptime and the busiest tools."""
    host, token, slug, workspace = _resolve(path, project)
    m = _call(host, token, "GET", f"/api/projects/{slug}/metrics", "read metrics", workspace=workspace)
    if as_json:
        _print_json(m)
        return
    rate = m["error_count"] / m["total_count"] if m["total_count"] else 0
    uptime = "n/a" if m.get("uptime") is None else f"{m['uptime'] * 100:.2f}%"
    p95 = "n/a" if m.get("p95_ms") is None else m["p95_ms"]
    typer.echo(
        f"{slug}, last {m['window_days']} days: {m['total_count']} calls, {rate * 100:.1f}% errors, "
        f"p95 {p95} ms, uptime {uptime}"
    )
    for t in m["tools"][:10]:
        typer.echo(f"  {t['tool']:<32} {t['count']:>8} calls {t['error_count']:>6} errors")
    for e in m["errors"][:5]:
        typer.secho(f"  {e['tool']}: {e['example']} (x{e['count']})", fg=typer.colors.RED)


@app.command()
def usage(
    path: Path = typer.Argument(Path("."), help="Linked repo directory (default: current)."),
    project: Optional[str] = typer.Option(None, "--project", help="Read this slug's usage."),
    as_json: bool = typer.Option(False, "--json", help="Print the combined responses."),
) -> None:
    """Calls by client, distinct signed-in callers, and the plan's monthly cap."""
    host, token, slug, workspace = _resolve(path, project)
    base = f"/api/projects/{slug}"
    row = _call(host, token, "GET", base, "read the project", workspace=workspace)
    m = _call(host, token, "GET", f"{base}/metrics", "read metrics", workspace=workspace)
    users = _call(host, token, "GET", f"{base}/metrics/users", "read callers", workspace=workspace)
    cap = row.get("tool_call_usage")
    if as_json:
        _print_json({
            "surfaces": m["surfaces"],
            "distinct_callers": len(users["users"]),
            "distinct_callers_truncated": users["truncated"],
            "detail_days": users["detail_days"],
            "tool_call_usage": cap,
        })
        return
    for s in m["surfaces"]:
        typer.echo(f"{s['surface']:<16} {s['count']} calls")
    more = "+" if users["truncated"] else ""
    typer.echo(f"{len(users['users'])}{more} distinct signed-in callers in {users['detail_days']} days")
    typer.echo(f"plan cap: {cap['used']} of {cap['limit']} tool calls this month" if cap else "no monthly tool-call cap")


@app.command()
def sessions(
    session: Optional[str] = typer.Argument(None, help="Show this session's calls in order."),
    path: Path = typer.Option(Path("."), "--path", help="Linked repo directory (default: current)."),
    project: Optional[str] = typer.Option(None, "--project", help="Read this slug's sessions."),
    as_json: bool = typer.Option(False, "--json", help="Print the API response."),
) -> None:
    """Recent MCP sessions with client and loop/retry flags, or one session's calls."""
    host, token, slug, workspace = _resolve(path, project)
    base = f"/api/projects/{slug}/metrics/sessions"
    if session:
        # Clients choose session ids, so they can hold a `/`.
        s = _call(host, token, "GET", f"{base}/{quote(session, safe='')}", "read the session", workspace=workspace)
        if as_json:
            _print_json(s)
            return
        for c in s["calls"]:
            typer.echo(f"{c['ts']} {c['tool']} {'ok' if c['ok'] else 'failed'} {c['duration_ms']} ms")
            if c.get("error"):
                typer.secho(f"    {c['error']}", fg=typer.colors.RED)
        return
    r = _call(host, token, "GET", base, "list sessions", workspace=workspace)
    if as_json:
        _print_json(r)
        return
    if not r["sessions"]:
        typer.echo(f"no sessions in the last {r['detail_days']} days")
    for x in r["sessions"]:
        client = " ".join(filter(None, [x.get("client_name") or "unknown", x.get("client_version")]))
        flags = f" [{', '.join(x['flags'])}]" if x.get("flags") else ""
        typer.echo(
            f"{x['session_id']}  {client}: {x['call_count']} calls, {x['error_count']} errors, "
            f"{x['started_at']} - {x['last_seen']}{flags}"
        )


@app.command()
def scan(
    path: Path = typer.Argument(Path("."), help="Linked repo directory (default: current)."),
    project: Optional[str] = typer.Option(None, "--project", help="Read this slug's scan."),
    as_json: bool = typer.Option(False, "--json", help="Print the API response."),
) -> None:
    """Known vulnerabilities in the project's own dependencies."""
    host, token, slug, workspace = _resolve(path, project)
    r = _call(host, token, "GET", f"/api/projects/{slug}/image-scan", "read the image scan", workspace=workspace)
    if as_json:
        _print_json(r)
        return
    if r["status"] != "complete":
        typer.echo(f"{slug}: {r['status']}" + (f" - {r['error']}" if r.get("error") else ""))
        return
    typer.echo(
        f"{slug}: {r['critical']} critical, {r['high']} high, {r['medium']} medium, {r['low']} low "
        f"(deploys blocked at {r['block_severity']})"
    )
    dismissed = {d["id"] for d in r.get("dismissed", [])}
    for f in r["findings"]:
        if f["id"] in dismissed:
            continue
        fix = f"fixed in {f['fixed']}" if f.get("fixed") else "no fix available"
        typer.echo(f"  {f['id']} ({f['severity']}) {f['package']}@{f['installed']} - {fix}")
    if r.get("resolve_prompt"):
        typer.echo(f"\nTo resolve with AI, paste:\n\n{r['resolve_prompt']}")


@app.command()
def readiness(
    path: Path = typer.Argument(Path("."), help="Linked repo directory (default: current)."),
    project: Optional[str] = typer.Option(None, "--project", help="Check this slug."),
    as_json: bool = typer.Option(False, "--json", help="Print the API response."),
) -> None:
    """Check a live server against the ChatGPT, Claude, MCP registry and Cursor listings."""
    host, token, slug, workspace = _resolve(path, project)
    r = _call(host, token, "GET", f"/api/projects/{slug}/readiness", "read the readiness report", workspace=workspace)
    if as_json:
        _print_json(r)
        return
    for store, s in r["stores"].items():
        typer.echo(f"{store}: {s['blockers']} blockers, {s['warnings']} warnings")
    for f in r["findings"]:
        tool = f" ({f['tool']})" if f.get("tool") else ""
        typer.echo(f"  [{f['severity']}] {f['rule']}{tool}: {f['detail']} - {', '.join(f['stores'])}")


@app.command()
def connect(
    path: Path = typer.Argument(Path("."), help="Linked repo directory (default: current)."),
    project: Optional[str] = typer.Option(None, "--project", help="Connect this slug."),
) -> None:
    """How to add the deployed server to ChatGPT, Claude or Cursor."""
    host, token, slug, workspace = _resolve(path, project)
    row = _call(host, token, "GET", f"/api/projects/{slug}", "read the project", workspace=workspace)
    url = normalize_url(row["url"])
    typer.echo(f"MCP URL: {url}")
    if row["auth_mode"] == "none":
        typer.echo("The endpoint is public: no credentials needed.")
    elif row["auth_mode"] == "token":
        typer.echo("The endpoint needs its bearer token, shown in the dashboard under the project's settings.")
    else:
        issuer = row.get("oauth_issuer") or "the workspace identity provider"
        client = f" with client id {row['oauth_client_id']}" if row.get("oauth_client_id") else ""
        typer.echo(f"The endpoint uses OAuth: clients sign in through {issuer}{client}.")
    typer.echo(f"ChatGPT: Settings → Apps & Connectors → Create, with MCP server URL {url}")
    typer.echo(f"Claude:  Settings → Connectors → Add custom connector, with URL {url}")
    typer.echo(f'Cursor:  .cursor/mcp.json: {{"mcpServers": {{"{slug}": {{"url": "{url}"}}}}}}')
