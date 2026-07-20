from __future__ import annotations

from importlib.metadata import version

import typer

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
def check() -> None:
    """Validate a project against foro.sh's deploy contract."""
    typer.echo("foro check: not implemented yet - see foro-sh/foro#4")


@app.command()
def init() -> None:
    """Scaffold a new MCP server, or add foro.yaml to an existing one."""
    typer.echo("foro init: not implemented yet - see foro-sh/foro#6")


@app.command()
def dev() -> None:
    """Run the server locally the way foro.sh will."""
    typer.echo("foro dev: not implemented yet - see foro-sh/foro#7")
