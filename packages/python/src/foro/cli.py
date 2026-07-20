from __future__ import annotations

import re
import subprocess
from importlib.metadata import version
from pathlib import Path
from typing import Optional

import typer

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
from foro._python_project import DEPENDENCY_MANAGERS
from foro.check import run_check
from foro.dev import DevError, run_dev
from foro.init import (
    ManifestFields,
    detect_entrypoint_candidates,
    detect_existing_dependency_manager,
    existing_manifest_diff,
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


def _prompt_name(default: str) -> str:
    while True:
        value = typer.prompt("Project name", default=default)
        if NAME_RE.match(value):
            return value
        typer.secho(f"Name must match {NAME_RE.pattern}", fg=typer.colors.RED)


def _prompt_entrypoint(default: str) -> str:
    while True:
        value = typer.prompt("Entrypoint", default=default)
        if value.endswith(".py") and is_valid_entrypoint(value):
            return value
        typer.secho(
            "Entrypoint must be a relative .py path within the project "
            "(no `..` traversal or shell metacharacters)",
            fg=typer.colors.RED,
        )


def _prompt_python_version(default: str) -> str:
    while True:
        value = typer.prompt(f"Python version ({'/'.join(PYTHON_VERSIONS)})", default=default)
        if value in PYTHON_VERSIONS:
            return value
        typer.secho(f"Must be one of {', '.join(PYTHON_VERSIONS)}", fg=typer.colors.RED)


def _prompt_dependency_manager(default: str) -> str:
    while True:
        value = typer.prompt("Dependency manager", default=default)
        if value in DEPENDENCY_MANAGERS:
            return value
        typer.secho(f"Must be one of {', '.join(DEPENDENCY_MANAGERS)}", fg=typer.colors.RED)


def _prompt_port(default: int) -> int:
    while True:
        value = typer.prompt("Port", default=default, type=int)
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
) -> None:
    """Scaffold a new MCP server, or add foro.yaml to an existing one."""
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
    git_init = typer.confirm("Initialize a git repo here?", default=True)

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
        if not typer.confirm("Overwrite?", default=False):
            typer.echo("Aborted.")
            raise typer.Exit(code=1)

    write_manifest(dir_path, fields)
    typer.secho(f"✓ wrote {dir_path / 'foro.yaml'}", fg=typer.colors.GREEN)


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
