from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import webbrowser
from importlib.metadata import version
from pathlib import Path
from typing import Optional

import typer

from foro import _config
from foro._api import ApiError
from foro._manifest import (
    DEFAULT_PORT,
    DEFAULT_PYTHON_VERSION,
    MAX_PORT,
    MIN_PORT,
    NAME_RE,
    PYTHON_VERSIONS,
    SIDECAR_PORT,
    ManifestError,
    is_valid_entrypoint,
)
from foro._mcp import DEFAULT_TIMEOUT as DEFAULT_HANDSHAKE_TIMEOUT
from foro._mcp import HandshakeError, handshake, normalize_url
from foro._python_project import DEPENDENCY_MANAGERS
from foro.auth import AuthError, fetch_identity, poll_for_token, revoke, start_device_flow
from foro.check import run_check
from foro.dev import DevError, run_dev
from foro.init import (
    ManifestFields,
    detect_entrypoint_candidates,
    detect_existing_dependency_manager,
    existing_manifest_diff,
    init_git_repo,
    scaffold_new,
    write_manifest,
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
        if value.endswith(".py") and is_valid_entrypoint(value):
            return value
        typer.secho(
            "Entrypoint must be a relative .py path within the project "
            "(no `..` traversal or shell metacharacters)",
            fg=typer.colors.RED,
        )


def _prompt_python_version(default: str) -> str:
    while True:
        value = _prompt(f"Python version ({'/'.join(PYTHON_VERSIONS)})", default=default)
        if value in PYTHON_VERSIONS:
            return value
        typer.secho(f"Must be one of {', '.join(PYTHON_VERSIONS)}", fg=typer.colors.RED)


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
        help="Directory to scaffold a new project into. Omit to add foro.yaml "
        "to the current directory instead.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Accept every default instead of prompting, so init runs "
        "unattended (in CI, or when an agent drives it). An existing "
        "foro.yaml is still never overwritten.",
    ),
) -> None:
    """Scaffold a new MCP server, or add foro.yaml to an existing one."""
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
            "argument inside it to add just a foro.yaml",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    name = _prompt_name(_sanitize_name(target.name))
    python_version = _prompt_python_version(DEFAULT_PYTHON_VERSION)
    port = _prompt_port(DEFAULT_PORT)
    git_init = _confirm("Initialize a git repo here?", default=True)

    # Fixed, opinionated structure (app.py + tools/) - not a free-form
    # filename choice like existing-repo mode's entrypoint. See
    # scaffold_new's docstring.
    fields = ManifestFields(name=name, entrypoint="server.py", python_version=python_version, port=port)
    scaffold_new(target, fields, git_init=git_init)

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
    python_version = _prompt_python_version(DEFAULT_PYTHON_VERSION)
    port = _prompt_port(DEFAULT_PORT)

    fields = ManifestFields(
        name=name,
        entrypoint=entrypoint,
        python_version=python_version,
        port=port,
        # Only recorded as an explicit override when it differs from what
        # the platform would auto-detect anyway (or when nothing could be
        # auto-detected) - redundant otherwise.
        dependency_manager=dependency_manager if dependency_manager != detected_manager else None,
    )

    diff = existing_manifest_diff(dir_path, fields)
    if diff:
        typer.echo("foro.yaml already exists. Diff:")
        typer.echo(diff)
        if not _confirm("Overwrite?", default=False):
            typer.echo("Aborted.")
            raise typer.Exit(code=1)

    write_manifest(dir_path, fields)
    typer.secho(f"✓ wrote {dir_path / 'foro.yaml'}", fg=typer.colors.GREEN)

    # Not already a repo, and deploying to foro.sh means pushing to GitHub -
    # worth asking here too, not just in from-scratch mode.
    if not (dir_path / ".git").exists() and _confirm("Initialize a git repo here?", default=True):
        init_git_repo(dir_path)


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
    except DevError as err:
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
        help="Read a token from stdin instead of running the device flow, for CI.",
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

    existing = _config.load(host)
    if existing and not force:
        who = f" as {existing.user}" if existing.user else ""
        if not typer.confirm(f"Already logged in to {host}{who}. Log in again?", default=False):
            raise typer.Exit(code=1)

    if with_token:
        token = sys.stdin.read().strip()
        if not token:
            typer.secho("✗ no token on stdin", fg=typer.colors.RED)
            raise typer.Exit(code=1)
        token_id = None
    else:
        token, token_id = _run_device_flow(host)

    try:
        identity = fetch_identity(host, token)
    except ApiError as err:
        typer.secho(f"✗ the token was rejected by {host}: {err}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from None

    _config.save(
        host,
        _config.Credentials(
            token=token, user=identity.user, workspace=identity.workspace, token_id=token_id
        ),
    )
    workspace = f" (workspace: {identity.workspace})" if identity.workspace else ""
    typer.secho(f"✓ Logged in as {identity.user}{workspace}", fg=typer.colors.GREEN)


def _run_device_flow(host: str) -> tuple[str, str | None]:
    try:
        grant = start_device_flow(host, label=socket.gethostname())
    except ApiError as err:
        typer.secho(f"✗ {err}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from None

    typer.secho(f"! First copy your one-time code: {grant.user_code}", fg=typer.colors.YELLOW)
    typer.echo(f"Press Enter to open {host} in your browser... (or paste {grant.verification_uri_complete})")
    try:
        input()
        webbrowser.open(grant.verification_uri_complete)

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
    return payload["access_token"], payload.get("token_id")


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
    typer.echo(f"    Token: {creds.token[:13]}… ({where})")


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

    if creds.token_id:
        try:
            revoke(host, creds.token, creds.token_id)
            typer.secho("✓ Logged out; token revoked", fg=typer.colors.GREEN)
        except ApiError as err:
            # Deleting locally regardless is the point - an offline or
            # already-revoked token must not strand the credential on disk.
            typer.secho(f"warning: could not revoke server-side ({err})", fg=typer.colors.YELLOW)
            typer.secho("✓ Logged out locally; revoke it on /account", fg=typer.colors.GREEN)
    else:
        typer.secho(
            "✓ Logged out locally. The token was supplied directly, so its id is unknown - "
            "revoke it on /account if it should stop working.",
            fg=typer.colors.GREEN,
        )

    _config.delete(host)


@auth_app.command("token")
def auth_token() -> None:
    """Print the raw token, for `curl -H "Authorization: Bearer $(foro auth token)"`."""
    _, creds = _require_credentials()
    typer.echo(creds.token)
