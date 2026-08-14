"""`foro init` - scaffold a new MCP server, or record the little a project
can't infer into the `pyproject.toml` it already has.

From-scratch mode (a `name` is given, per foro-sh/foro#6): generate a
minimal working project - always uv-based, since a freshly generated project
has no dependency-manager ambiguity to resolve (that's what
`dependency_manager` is for - see below). Its output is guaranteed to pass
`foro check` (the golden round-trip: init -> check -> serves - see
tests/test_init_dev_roundtrip.py), and it carries no `[tool.foro]` table at
all: a scaffold is by construction the shape the platform infers.

Existing-repo mode (no `name`, run inside a project that already has code):
detect instead of prompting blind, reusing the platform's own detection
signal (`_python_project.detect_dependency_manager`) so the pre-filled
answer matches what the platform would infer at deploy time. Only the
`[tool.foro]` table in `pyproject.toml` is written, and only when the answers
differ from what deploy-time inference would produce anyway - never any
source file.

All interactive prompting lives in cli.py; this module is pure logic so it's
testable without a terminal attached.
"""

from __future__ import annotations

import difflib
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from foro._manifest import (
    DEFAULT_PORT,
    DEFAULT_RUNTIME,
    DEFAULT_RUNTIME_VERSIONS,
    PYTHON_ENTRYPOINT_CANDIDATES,
)
from foro._proc import MissingToolError
from foro._proc import run as _run
from foro._python_project import DependencyManagerError, detect_dependency_manager

# The platform's own entry-file list, checked here in the same order - an
# entrypoint it would find is one nothing has to be written down for. Only
# files that also look like an MCP entrypoint count as a hit.
ENTRYPOINT_CANDIDATES = PYTHON_ENTRYPOINT_CANDIDATES


@dataclass
class ManifestFields:
    name: str
    entrypoint: str
    runtime: str = DEFAULT_RUNTIME
    runtime_version: str = DEFAULT_RUNTIME_VERSIONS[DEFAULT_RUNTIME]
    port: int = DEFAULT_PORT
    dependency_manager: str | None = None


def detect_entrypoint_candidates(dir_path: Path) -> list[str]:
    """A candidate's content is checked for two markers, in priority order:

    - `foro.run(` - only the real entrypoint ever calls this, so its
      presence is decisive on its own. This is what a scaffold_new project's
      server.py has (FastMCP construction lives in app.py, which never
      calls foro.run) - without this priority, app.py would also match the
      broader FastMCP( check below and produce a false double-hit.
    - `FastMCP(` - a weaker fallback for a flat, single-file server that
      constructs and runs everything in one place without foro.run (e.g.
      calls `mcp.run()` directly).

    Whenever any candidate matches on `foro.run(`, that's authoritative and
    the weaker matches are discarded.
    """
    run_hits = []
    fastmcp_hits = []
    for candidate in ENTRYPOINT_CANDIDATES:
        path = dir_path / candidate
        if not path.is_file():
            continue
        text = path.read_text(errors="ignore")
        if "foro.run(" in text:
            run_hits.append(candidate)
        elif "FastMCP(" in text:
            fastmcp_hits.append(candidate)
    return run_hits or fastmcp_hits


def detect_existing_dependency_manager(dir_path: Path) -> str | None:
    try:
        return detect_dependency_manager(dir_path)
    except DependencyManagerError:
        return None


class MissingPyprojectError(Exception):
    """There is no pyproject.toml to write the `[tool.foro]` table into."""


# A `[tool.foro]` table runs to the next table header. Good enough for a file
# a person wrote: the pathological case is a bare `[` starting a line inside a
# multi-line array, which no formatter produces.
_FORO_TABLE_RE = re.compile(r"^\[tool\.foro\]\n(?:(?!\[).*\n?)*", re.MULTILINE)


def foro_table(fields: ManifestFields) -> str | None:
    """The `[tool.foro]` table these answers need, or None when they need
    none. Only values deploy-time inference can't reach are written: the
    entrypoint when it isn't one of the files the platform looks for, a
    non-default port, an interpreter pinned away from the default, and a
    `dependency_manager` override. Writing anything else back would be
    restating what pyproject.toml already says, one copy to drift out of
    date."""
    lines = []
    if fields.entrypoint not in ENTRYPOINT_CANDIDATES:
        lines.append(f'entrypoint = "{fields.entrypoint}"')
    if fields.runtime_version != DEFAULT_RUNTIME_VERSIONS[fields.runtime]:
        lines.append(f'runtime_version = "{fields.runtime_version}"')
    if fields.port != DEFAULT_PORT:
        lines.append(f"port = {fields.port}")
    if fields.dependency_manager:
        lines.append(f'dependency_manager = "{fields.dependency_manager}"')
    if not lines:
        return None
    return "[tool.foro]\n" + "\n".join(lines) + "\n"


def existing_foro_table_diff(dir_path: Path, fields: ManifestFields) -> str | None:
    """None if pyproject.toml carries no `[tool.foro]` table to protect.
    Otherwise a unified diff of the current table against what init would
    write - the "confirm or diff" the platform's issue text asks for."""
    pyproject = dir_path / "pyproject.toml"
    if not pyproject.is_file():
        return None
    match = _FORO_TABLE_RE.search(pyproject.read_text())
    if match is None:
        return None
    old = match.group().splitlines(keepends=True)
    new = (foro_table(fields) or "").splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(old, new, fromfile="current [tool.foro]", tofile="new [tool.foro]")
    )


def write_foro_table(dir_path: Path, fields: ManifestFields) -> bool:
    """Add or replace the `[tool.foro]` table in pyproject.toml. False when
    there was nothing to write - the common case, and the one worth telling
    the user about, since it means the repo already deploys as it stands."""
    pyproject = dir_path / "pyproject.toml"
    if not pyproject.is_file():
        raise MissingPyprojectError(
            f"no pyproject.toml in {dir_path} - foro reads a Python project's config from "
            "it, so create one (`uv init`) before adding foro settings"
        )

    table = foro_table(fields)
    text = pyproject.read_text()
    existing = _FORO_TABLE_RE.search(text)
    if table is None:
        if existing is None:
            return False
        # Answers that now match inference: drop the table rather than leave a
        # stale one behind.
        pyproject.write_text(text[: existing.start()] + text[existing.end() :])
        return True

    if existing is not None:
        pyproject.write_text(text[: existing.start()] + table + text[existing.end() :])
    else:
        pyproject.write_text(text.rstrip("\n") + "\n\n" + table)
    return True


# Modular by default (per FastMCP's own tool-organization guidance: one
# file per tool, registered against a shared instance): `app.py` owns the
# FastMCP instance so tool modules and the entrypoint can both import it
# without a cycle; `server.py` (the entrypoint the platform looks for)
# stays thin, only responsible for pulling `tools/` in for its
# registration side effects and calling foro.run. Two files instead of one
# is the smallest structure that avoids `tools/add.py` needing to import
# back from the entrypoint it's imported by.
#
# Registration is a side effect of importing a tool module, which makes it
# easy to break silently - a server missing its tools starts and serves
# perfectly well, and only looks broken from the client. Two things guard
# that: `load_tools()` is a real call rather than a bare `import tools`, so
# it neither reads as dead code nor trips F401 (an unused-import autofix
# would otherwise happily delete the line that makes the server work), and
# it discovers modules itself, so a new file in `tools/` can't be left
# unregistered. tests/test_tools.py asserts the wiring on top of that.
_APP_TEMPLATE = '''from fastmcp import FastMCP

mcp = FastMCP("{name}")
'''

_SERVER_TEMPLATE = '''import foro
from app import mcp
from tools import load_tools

load_tools()  # registers every tool in tools/ against `mcp`

if __name__ == "__main__":
    foro.run(mcp)
'''

_TOOLS_INIT_TEMPLATE = '''"""One file per tool. Drop a new file in this directory and decorate its
function with @mcp.tool (importing `mcp` from `app`) - load_tools() finds
it, so there is no import list here to keep in sync. Modules whose name
starts with an underscore are skipped, for shared helpers that aren't
tools themselves.
"""

import importlib
import pkgutil


def load_tools() -> list[str]:
    """Import every tool module for its registration side effect: importing
    it is what runs its @mcp.tool decorators. Returns the module names that
    were loaded, so a caller (or a test) can tell registration actually
    happened instead of trusting a silent import."""
    loaded = []
    for _, name, _ in pkgutil.iter_modules(__path__):
        if name.startswith("_"):
            continue
        importlib.import_module(f"{__name__}.{name}")
        loaded.append(name)
    return loaded
'''

_TOOL_ADD_TEMPLATE = '''from app import mcp


@mcp.tool
def add(a: int, b: int) -> int:
    return a + b
'''

# __ENTRYPOINT__ is substituted with the entrypoint's module name rather
# than .format()ed in - the body is full of braces (set comprehension, f-string).
_TEST_TOOLS_TEMPLATE = '''import subprocess
import sys
from pathlib import Path

from tools.add import add

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_add():
    assert add(2, 3) == 5


def test_entrypoint_registers_every_tool():
    """Guards the wiring rather than the logic. A tool registers as a side
    effect of its module being imported, so an entrypoint that stops calling
    load_tools(), or a tool file that never gets discovered, still starts up
    perfectly well and serves nothing - a failure that stays invisible until
    a client asks for a tool. This turns it into a test failure instead.

    The probe runs in a fresh interpreter on purpose. Registration mutates
    one shared `mcp` object, and this file's own `from tools.add import add`
    already registers `add` in the pytest process - asserting in here would
    pass whatever the entrypoint does. A clean process imports nothing but
    the entrypoint, so what comes back is exactly what a deployed server
    would serve."""
    probe = (
        "import asyncio, importlib;"
        "importlib.import_module('__ENTRYPOINT__');"
        "from app import mcp;"
        "print(' '.join(t.name for t in asyncio.run(mcp.list_tools())))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=_PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert "add" in result.stdout.split(), result.stdout
'''

_PYPROJECT_TEMPLATE = '''[project]
name = "{name}"
version = "0.1.0"
requires-python = ">={python_version}"
dependencies = ["fastmcp", "foro"]

[dependency-groups]
dev = ["pytest>=8.0"]

[tool.pytest.ini_options]
# tests/ has no __init__.py (flat layout) - without this, pytest's default
# rootdir-based import resolution won't put the project root (where app.py
# and tools/ live) on sys.path, and `from tools.add import add` in
# tests/test_tools.py fails with ModuleNotFoundError.
pythonpath = ["."]
'''

_README_TEMPLATE = '''# {name}

An MCP server, deployable on [foro.sh](https://foro.sh).

## Structure

- `app.py` - the FastMCP server instance, shared by every tool module
- `tools/` - one file per tool; add a new tool by dropping a file in here
  and decorating its function with `@mcp.tool`. `load_tools()` picks it up
  automatically, so there's no import list to maintain
- `server.py` - the deploy entrypoint (the name foro looks for - don't rename)

## Develop

```bash
uv tool install foro   # once
foro dev               # runs the server exactly as foro.sh will
```

Copy `.env.example` to `.env` and fill in any secrets your tools need -
`foro dev` loads it automatically for local runs. In production these are
set as Secrets in the foro.sh dashboard instead - `.env` is never deployed.

## Test

```bash
uv run pytest
```

## Deploy

Push this repo to GitHub, then connect it from the foro.sh dashboard.
'''

_GITIGNORE_TEMPLATE = '''.venv/
__pycache__/
*.pyc
.env
.pytest_cache/
.DS_Store
'''

_ENV_EXAMPLE_TEMPLATE = '''# Copy to .env for local development - foro dev loads it automatically.
# Never commit the real .env; in production these are set as Secrets in
# the foro.sh dashboard instead, and read the same way via foro.secret().
#
# EXAMPLE_API_KEY=
'''


class ScaffoldError(Exception):
    """Scaffolding could not be completed. Whatever it had written is gone by
    the time this is raised."""


def scaffold_new(dir_path: Path, fields: ManifestFields, git_init: bool = False) -> None:
    """Write a from-scratch project: app.py, server.py (the entrypoint the
    platform looks for), tools/, pyproject.toml, a locked uv.lock (`uv lock`,
    so the golden round-trip - init's output must pass check - holds without
    a manual step), README.md, .gitignore,
    .env.example, and tests/.

    All or nothing: `uv lock` runs last and can fail, and the leftovers used
    to block the retry with "already exists and is not empty".
    """
    # Only remove what this call created - scaffold_new is callable on its
    # own and must not take a user's directory with it.
    created_root = not dir_path.exists()
    written: list[Path] = []

    def write(path: Path, text: str) -> None:
        path.write_text(text)
        written.append(path)

    dir_path.mkdir(parents=True, exist_ok=True)
    tools_dir = dir_path / "tools"
    tests_dir = dir_path / "tests"
    tools_dir.mkdir(parents=True, exist_ok=True)
    tests_dir.mkdir(parents=True, exist_ok=True)

    try:
        write(dir_path / "app.py", _APP_TEMPLATE.format(name=fields.name))
        write(dir_path / fields.entrypoint, _SERVER_TEMPLATE)
        write(tools_dir / "__init__.py", _TOOLS_INIT_TEMPLATE)
        write(tools_dir / "add.py", _TOOL_ADD_TEMPLATE)
        write(
            tests_dir / "test_tools.py",
            _TEST_TOOLS_TEMPLATE.replace("__ENTRYPOINT__", Path(fields.entrypoint).stem),
        )
        write(
            dir_path / "pyproject.toml",
            # {python_version} is pyproject's own `requires-python`, not the
            # manifest field - scaffold_new only ever writes Python projects,
            # so the runtime's version is the right value to put there.
            _PYPROJECT_TEMPLATE.format(name=fields.name, python_version=fields.runtime_version),
        )
        write(dir_path / "README.md", _README_TEMPLATE.format(name=fields.name))
        write(dir_path / ".gitignore", _GITIGNORE_TEMPLATE)
        write(dir_path / ".env.example", _ENV_EXAMPLE_TEMPLATE)

        try:
            _run(["uv", "lock"], cwd=dir_path, check=True)
        except MissingToolError as err:
            raise ScaffoldError(
                f"{err}. A scaffolded project is locked with `uv lock`, and foro dev "
                "runs it with `uv run`."
            ) from None
        except subprocess.CalledProcessError as err:
            raise ScaffoldError(
                f"`uv lock` failed in {dir_path}:\n{(err.stderr or '').strip()}"
            ) from None
    except BaseException:
        _remove_scaffold(dir_path, written, created_root)
        raise

    if git_init:
        init_git_repo(dir_path)


def _remove_scaffold(dir_path: Path, written: list[Path], created_root: bool) -> None:
    if created_root:
        shutil.rmtree(dir_path, ignore_errors=True)
        return
    # Take back only what was written, plus our two now-empty directories.
    for path in written:
        path.unlink(missing_ok=True)
    for name in ("tools", "tests"):
        directory = dir_path / name
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()


class GitInitError(Exception):
    """`git init` could not run. Never fatal to the project itself - the files
    are written and valid, they are simply not a repo yet."""


def init_git_repo(dir_path: Path) -> None:
    try:
        _run(["git", "init"], cwd=dir_path, check=True)
    except MissingToolError as err:
        raise GitInitError(str(err)) from None
    except subprocess.CalledProcessError as err:
        raise GitInitError(f"`git init` failed: {(err.stderr or '').strip()}") from None
