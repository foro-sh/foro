from __future__ import annotations

from importlib.metadata import version
from pathlib import Path

import typer

from foro.check import run_check

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


@app.command()
def init() -> None:
    """Scaffold a new MCP server, or add foro.yaml to an existing one."""
    typer.echo("foro init: not implemented yet - see foro-sh/foro#6")


@app.command()
def dev() -> None:
    """Run the server locally the way foro.sh will."""
    typer.echo("foro dev: not implemented yet - see foro-sh/foro#7")
