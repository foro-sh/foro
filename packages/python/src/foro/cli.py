from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import threading
import webbrowser
from importlib.metadata import version
from pathlib import Path
from typing import Optional

import typer

from foro import _api, _config, _project_link, projects
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
    poll_for_token,
    revoke,
    start_device_flow,
)
from foro.check import run_check
from foro.deploy import DeployError, get_deployment, stream_build, stream_deploy
from foro.deploy import deploy as deploy_project
from foro.logs import latest_deployment_id, read_deployment, read_runtime, stream_runtime
from foro.projects import ProjectError, get_project, list_deployments, list_projects
from foro.projects import link as link_project
from foro.dev import DevError, run_dev
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


@app.callback()
def main(
    show_version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the foro CLI version and exit.",
    ),
) -> None:
    """foro - the foro.sh Python SDK and CLI."""


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
    """A directory basename isn't guaranteed to be a valid `name:` - lowercase
    it and collapse anything outside [a-z0-9-] so the prompt's default is
    actually acceptable if the user just hits enter."""
    slug = re.sub(r"[^a-z0-9-]+", "-", raw.lower()).strip("-")
    return slug[:48] or "my-server"


# ponytail: a module global rather than a `yes` parameter threaded through
# both init modes and all six prompt helpers - `--yes` is set once, at the
# only entrypoint that can set it.
_assume_yes = False


def _prompt(*args, default, **kwargs):
    """Under `--yes`, every prompt answers itself with its default. The
    defaults are the same values the validation loops accept, so callers keep
    their loop and simply pass through on the first iteration."""
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
    # Versions are allowlisted per runtime, so the prompt is too. There is no
    # runtime prompt yet: with one runtime, asking would be a question with a
    # single valid answer.
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

    # Fixed, opinionated structure (app.py + tools/) - not a free-form
    # filename choice like existing-repo mode's entrypoint. See
    # scaffold_new's docstring.
    fields = ManifestFields(name=name, entrypoint="server.py", runtime_version=runtime_version, port=port)
    try:
        scaffold_new(target, fields, git_init=git_init)
    except ScaffoldError as err:
        typer.secho(f"✗ {err}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from None
    except GitInitError as err:
        # The project is written and valid; only the repo is missing.
        typer.secho(f"warning: {err}", fg=typer.colors.YELLOW)

    typer.secho(f"✓ scaffolded {target}", fg=typer.colors.GREEN)
    typer.echo(f"  cd {target} && foro dev")


def _init_existing(dir_path: Path) -> None:
    candidates = detect_entrypoint_candidates(dir_path)
    if len(candidates) > 1:
        typer.echo("Multiple candidate entrypoints found: " + ", ".join(candidates))
    entrypoint_default = candidates[0] if candidates else "server.py"
    entrypoint = _prompt_entrypoint(entrypoint_default)

    # Reuses the platform's own detection signal so the pre-filled answer
    # matches what the platform would infer at deploy time - see
    # detect_existing_dependency_manager's docstring.
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
        # Only recorded as an explicit override when it differs from what
        # the platform would auto-detect anyway (or when nothing could be
        # auto-detected) - redundant otherwise.
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
        # Nothing to write is the good outcome, not a no-op worth apologising
        # for: the platform infers every answer given.
        typer.secho("✓ nothing to configure - this project deploys as it is", fg=typer.colors.GREEN)

    # Not already a repo, and deploying to foro.sh means pushing to GitHub -
    # worth asking here too, not just in from-scratch mode.
    if not (dir_path / ".git").exists() and _confirm("Initialize a git repo here?", default=True):
        try:
            init_git_repo(dir_path)
        except GitInitError as err:
            # The config is already written, which is all this mode promises.
            typer.secho(f"warning: {err}", fg=typer.colors.YELLOW)


@app.command()
def dev(
    path: Path = typer.Argument(Path("."), help="Repo directory to run (default: current directory)."),
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
    typer.echo("Press Ctrl+C to stop.")

    try:
        process.wait()
    except KeyboardInterrupt:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


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

    # Read stdin before anything can prompt on it - the confirm below would
    # otherwise eat the token as its answer.
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

    _config.save(
        host,
        _config.Credentials(token=token, user=identity.user, workspace=identity.workspace),
    )
    workspace = f" (workspace: {identity.workspace})" if identity.workspace else ""
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
    """Best effort - it raises on a box with no browser, which is exactly
    where the printed URL is the point."""
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
        # No terminal to press Enter on. The grant still works from any
        # browser, so print the URL and poll rather than dying on EOFError.
        typer.echo(f"Open this to authorize: {grant.verification_uri_complete}")
    try:
        if interactive:
            try:
                input()
            except EOFError:
                # stdin was a tty when asked and closed underneath us.
                typer.echo("")
            _open_browser(grant.verification_uri_complete)

        # ponytail: a redrawn line, not a spinner library - it has to read as
        # progress rather than a hang, and that's all it takes. Skipped off a
        # terminal, where \r is just noise in a log.
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
    if identity.workspace:
        typer.echo(f"    Workspace: {identity.workspace}")
    # Same 8 characters of the random part that /account renders as
    # `token_prefix`, so you can tell which row on the dashboard is this
    # machine's before revoking it.
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
        # Deleting locally regardless is the point - an offline or
        # already-revoked token must not strand the credential on disk.
        typer.secho(f"warning: could not revoke server-side ({err})", fg=typer.colors.YELLOW)
        typer.secho("✓ Logged out locally; revoke it on /account", fg=typer.colors.GREEN)

    _config.delete(host)


@auth_app.command("token")
def auth_token() -> None:
    """Print the raw token, for `curl -H "Authorization: Bearer $(foro auth token)"`."""
    _, creds = _require_credentials()
    typer.echo(creds.token)




def _fail(err: ApiError, action: str) -> typer.Exit:
    typer.secho(f"✗ {_api.explain(err, action=action)}", fg=typer.colors.RED)
    return typer.Exit(code=1)


def _resolve(path: Path, project: str | None) -> tuple[str, str, str]:
    """Every project command needs the same three things: a host, a token, and
    the slug this directory acts on."""
    host, creds = _require_credentials()
    try:
        return host, creds.token, projects.resolve_slug(path, host, project)
    except ProjectError as err:
        typer.secho(f"✗ {err}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from None


@app.command()
def deploy(
    path: Path = typer.Argument(Path("."), help="Repo directory to deploy (default: current)."),
    project: Optional[str] = typer.Option(None, "--project", help="Deploy to this slug."),
    upload: bool = typer.Option(False, "--upload", help="Force uploading the working tree."),
    repo: bool = typer.Option(False, "--repo", help="Force building from the linked repo branch."),
    detach: bool = typer.Option(False, "--detach", "-d", help="Don't stream; print the URL and exit."),
    skip_check: bool = typer.Option(False, "--skip-check", help="Deploy without running foro check."),
) -> None:
    """Deploy this directory to foro.sh and stream the build."""
    if upload and repo:
        typer.secho("✗ --upload and --repo are mutually exclusive", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    host, creds = _require_credentials()

    # Never upload something that can't build - the platform would only tell
    # us the same thing 60 seconds later, from further away.
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
            on_step=lambda message: typer.echo(f"- {message}"),
        )
    except (DeployError, ArchiveError) as err:
        typer.secho(f"✗ {err}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from None
    except ApiError as err:
        raise _fail(err, "deploy") from None

    if started.created:
        typer.echo(f"- created {started.slug}")
        _offer_gitignore(path)

    typer.echo(f"- deploying {started.slug} ({started.deployment_id[:8]})")
    if detach:
        typer.echo(f"  {started.url}")
        return

    _stream_deploy(host, creds.token, started)


def _offer_gitignore(repo_dir: Path) -> None:
    if _project_link.is_gitignored(repo_dir):
        return
    if typer.confirm(f"Add {_project_link.GITIGNORE_ENTRY} to .gitignore?", default=True):
        _project_link.add_to_gitignore(repo_dir)


def _stream_deploy(host: str, token: str, started) -> None:
    """The deploy narrative in the foreground, raw build output behind it.

    Two channels, so two streams: the build log is where a failure's actual
    cause usually is, and waiting for the deploy stream to finish before
    showing it would defeat the point of watching.
    """
    build_lines: list[str] = []

    def pump_build() -> None:
        try:
            for entry in stream_build(host, token, started.slug, started.deployment_id):
                line = entry.get("line", "")
                build_lines.append(line)
                typer.secho(f"  │ {line}", dim=True)
        except ApiError:
            # The build channel is a nicety; losing it must not fail a deploy
            # that the deploy channel is still reporting on truthfully.
            pass

    pump = threading.Thread(target=pump_build, daemon=True)
    pump.start()

    try:
        for entry in stream_deploy(host, token, started.slug, started.deployment_id):
            typer.echo(entry.get("line", ""))
    except KeyboardInterrupt:
        typer.echo("")
        typer.secho(
            f"detached - the deploy is still running. `foro logs --deploy {started.deployment_id[:8]}` to follow it.",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(code=0) from None
    except ApiError as err:
        raise _fail(err, "stream the deploy") from None

    pump.join(timeout=2)

    try:
        final = get_deployment(host, token, started.slug, started.deployment_id)
    except ApiError as err:
        raise _fail(err, "read the deployment") from None

    if final["status"] == "live":
        typer.secho(f"✓ live at {started.url}", fg=typer.colors.GREEN)
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
    as_json: bool = typer.Option(False, "--json", help="One JSON object per line, for jq."),
) -> None:
    """Show a project's runtime logs, or one deployment's deploy/build log."""
    if deploy_log and build_log:
        typer.secho("✗ --deploy and --build are mutually exclusive", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    host, token, slug = _resolve(path, project)

    def emit(entry: dict) -> None:
        typer.echo(json.dumps(entry) if as_json else entry.get("line", ""))

    try:
        if deploy_log or build_log:
            deployment_id = deployment or latest_deployment_id(host, token, slug)
            if not deployment_id:
                typer.secho(f"✗ {slug} has no deployments yet", fg=typer.colors.RED)
                raise typer.Exit(code=1)
            kind = "build" if build_log else "deploy"
            for entry in read_deployment(host, token, slug, deployment_id, kind):
                emit(entry)
            return

        if follow:
            try:
                for entry in stream_runtime(host, token, slug):
                    emit(entry)
            except KeyboardInterrupt:
                typer.echo("")
            return

        lines = read_runtime(host, token, slug)
        if not lines:
            typer.echo(
                "no stored logs - retention is plan-gated (24h on Free), so this is "
                "normal for a quiet or recently deployed server"
            )
            return
        for entry in lines:
            emit(entry)
    except ApiError as err:
        raise _fail(err, "read logs") from None


# No `no_args_is_help`: bare `foro projects` is the list, not a help screen.
projects_app = typer.Typer(help="Inspect your foro.sh projects.")
app.add_typer(projects_app, name="projects")


@projects_app.callback(invoke_without_command=True)
def projects_default(ctx: typer.Context) -> None:
    """List every project in the token's workspace."""
    if ctx.invoked_subcommand is not None:
        return
    host, creds = _require_credentials()
    try:
        rows = list_projects(host, creds.token)
    except ApiError as err:
        raise _fail(err, "list projects") from None

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
    host, token, slug = _resolve(path, project)
    try:
        row = get_project(host, token, slug)
        history = list_deployments(host, token, slug)
    except ApiError as err:
        raise _fail(err, "read the project") from None

    typer.echo(row["slug"])
    typer.echo(f"  Name:    {row.get('name') or '(none)'}")
    typer.echo(f"  Status:  {'building' if row.get('building') else row['status']}")
    typer.echo(f"  Source:  {row['source']}")
    typer.echo(f"  URL:     {row['url']}")
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
    try:
        row = link_project(path, host, creds.token, slug)
    except ApiError as err:
        raise _fail(err, "link the project") from None

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
    host, token, slug = _resolve(path, project)
    try:
        row = get_project(host, token, slug)
    except ApiError as err:
        raise _fail(err, "read the project") from None

    typer.echo(row["url"])
    webbrowser.open(row["url"])
