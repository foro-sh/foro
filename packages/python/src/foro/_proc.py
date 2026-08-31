"""Running the external tools the CLI shells out to - `uv` and `git`.

A missing binary becomes a `MissingToolError` naming what to install, rather
than a `FileNotFoundError` naming an errno. Callers decide whether that is
fatal: `dev` cannot run a server without uv, `check` can skip one rule.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_INSTALL_HINTS = {
    "uv": "install it from https://docs.astral.sh/uv/getting-started/installation/",
    "git": "install it from https://git-scm.com/downloads",
}


class MissingToolError(Exception):
    """An external tool the CLI needs is not on PATH. `tool` is its name."""

    def __init__(self, tool: str) -> None:
        hint = _INSTALL_HINTS.get(tool, "install it and make sure it is on your PATH")
        super().__init__(f"`{tool}` is not installed or not on your PATH - {hint}")
        self.tool = tool


def run(argv: list[str], *, cwd: Path | str | None = None, check: bool = False):
    """`subprocess.run` with output captured, translating a missing binary.

    A tool that ran and failed is left to the caller - the right answer
    differs at every call site.
    """
    try:
        return subprocess.run(argv, cwd=cwd, check=check, capture_output=True, text=True)
    except FileNotFoundError:
        raise MissingToolError(argv[0]) from None


def popen(argv: list[str], **kwargs) -> subprocess.Popen:
    """`subprocess.Popen` with the same translation."""
    try:
        return subprocess.Popen(argv, **kwargs)
    except FileNotFoundError:
        raise MissingToolError(argv[0]) from None
