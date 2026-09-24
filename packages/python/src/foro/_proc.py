"""Run `uv` and `git`. A missing binary becomes MissingToolError."""

from __future__ import annotations

import subprocess
from pathlib import Path

_INSTALL_HINTS = {
    "uv": "install it from https://docs.astral.sh/uv/getting-started/installation/",
    "git": "install it from https://git-scm.com/downloads",
}


class MissingToolError(Exception):
    def __init__(self, tool: str) -> None:
        hint = _INSTALL_HINTS.get(tool, "install it and make sure it is on your PATH")
        super().__init__(f"`{tool}` is not installed or not on your PATH - {hint}")
        self.tool = tool


def run(argv: list[str], *, cwd: Path | str | None = None, check: bool = False):
    try:
        return subprocess.run(argv, cwd=cwd, check=check, capture_output=True, text=True)
    except FileNotFoundError:
        raise MissingToolError(argv[0]) from None


def popen(argv: list[str], **kwargs) -> subprocess.Popen:
    try:
        return subprocess.Popen(argv, **kwargs)
    except FileNotFoundError:
        raise MissingToolError(argv[0]) from None
