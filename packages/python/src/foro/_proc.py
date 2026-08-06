"""Running the external tools the CLI shells out to - `uv` and `git`.

Every one of those calls used to let a missing binary escape as a raw
`FileNotFoundError: [Errno 2] No such file or directory: 'uv'`, from four
places (`check`, `dev`, and `init` twice). That is a traceback, not an error
message: it names the errno rather than the thing to install, and it lands on
exactly the users least equipped to read it - `foro` is documented as
`pip install`-able, which does not bring `uv` with it.

So the one rule here: a missing tool is a `MissingToolError` carrying a
sentence the user can act on, and each caller decides whether that is fatal
(`dev` cannot run a server without `uv`) or a warning (`check` can validate
everything else and just not verify the lockfile).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

# What to tell someone who hasn't got the binary. Keyed by argv[0].
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

    Only `FileNotFoundError` is translated. A tool that ran and failed is a
    different question with a different answer at every call site, so its
    `CalledProcessError` (under `check=True`) or non-zero `returncode` is left
    for the caller.
    """
    try:
        return subprocess.run(argv, cwd=cwd, check=check, capture_output=True, text=True)
    except FileNotFoundError:
        raise MissingToolError(argv[0]) from None


def popen(argv: list[str], **kwargs) -> subprocess.Popen:
    """`subprocess.Popen` with the same translation. Deliberately passes
    **kwargs straight through - `dev` needs `env`, `cwd` and `stdin` on it,
    and none of that is this module's business."""
    try:
        return subprocess.Popen(argv, **kwargs)
    except FileNotFoundError:
        raise MissingToolError(argv[0]) from None
