"""`foro init` - scaffold a new MCP server, or add a `foro.yaml` to an
existing one.

From-scratch mode (a `name` is given, per foro-sh/foro#6): generate a
minimal working project - always uv-based, since a freshly generated project
has no dependency-manager ambiguity to resolve (that's what
`dependency_manager` in the manifest is for - see below). Its output is
guaranteed to pass `foro check` (the golden round-trip: init -> check ->
serves - see tests/test_init_dev_roundtrip.py).

Existing-repo mode (no `name`, run inside a project that already has code):
detect instead of prompting blind, reusing the platform's own detection
signal (`_python_project.detect_dependency_manager`) so the pre-filled
answer matches what the platform would infer at deploy time. Only
`foro.yaml` is written - never touches source files.

All interactive prompting lives in cli.py; this module is pure logic so it's
testable without a terminal attached.
"""

from __future__ import annotations

import difflib
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml as pyyaml

from foro._manifest import DEFAULT_PORT, DEFAULT_PYTHON_VERSION
from foro._proc import MissingToolError
from foro._proc import run as _run
from foro._python_project import DependencyManagerError, detect_dependency_manager

# Candidates checked in this order; only files that both exist and look like
# an MCP entrypoint count as a hit - mirrors the spirit of the platform's own
# detection, applied to entrypoints instead of dependency managers.
ENTRYPOINT_CANDIDATES = ["server.py", "main.py", "src/server.py", "app.py"]


@dataclass
class ManifestFields:
    name: str
    entrypoint: str
    python_version: str = DEFAULT_PYTHON_VERSION
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


def manifest_yaml(fields: ManifestFields) -> str:
    # name/entrypoint/python_version/port are always written explicitly,
    # even when they match the schema's own default - a foro.yaml should be
    # legible on its own without the reader needing to know the implicit
    # defaults. dependency_manager stays conditional: unlike the others,
    # merely mentioning it changes deploy behavior (it's an override, not a
    # value with an implicit default), so it's only written when it's a real
    # override from what auto-detection would find anyway.
    doc: dict[str, object] = {
        "name": fields.name,
        "entrypoint": fields.entrypoint,
        "python_version": fields.python_version,
        "port": fields.port,
    }
    if fields.dependency_manager:
        doc["dependency_manager"] = fields.dependency_manager
    return pyyaml.safe_dump(doc, sort_keys=False)


def existing_manifest_diff(dir_path: Path, fields: ManifestFields) -> str | None:
    """None if there's no existing foro.yaml to protect. Otherwise a unified
    diff of the current content against what init would write - the "confirm
    or diff" the platform's issue text asks for."""
    manifest_path = dir_path / "foro.yaml"
    if not manifest_path.is_file():
        return None
    old = manifest_path.read_text().splitlines(keepends=True)
    new = manifest_yaml(fields).splitlines(keepends=True)
    return "".join(difflib.unified_diff(old, new, fromfile="current foro.yaml", tofile="new foro.yaml"))


def write_manifest(dir_path: Path, fields: ManifestFields) -> None:
    (dir_path / "foro.yaml").write_text(manifest_yaml(fields))


# Modular by default (per FastMCP's own tool-organization guidance: one
# file per tool, registered against a shared instance): `app.py` owns the
# FastMCP instance so tool modules and the entrypoint can both import it
# without a cycle; `server.py` (the entrypoint - foro.yaml always points
# here) stays thin, only responsible for pulling `tools/` in for its
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
- `server.py` - the deploy entrypoint (referenced by `foro.yaml` - don't rename)

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
    """Write a from-scratch project: app.py, server.py (the entrypoint -
    foro.yaml always points here), tools/, pyproject.toml, foro.yaml, a
    locked uv.lock (`uv lock`, so the golden round-trip - init's output
    must pass check - holds without a manual step), README.md, .gitignore,
    .env.example, and tests/.

    All or nothing. `uv lock` runs last and can fail - no uv installed, or an
    unresolvable dependency set - and it used to leave every other file behind
    on the way out, so `foro init` reported failure while creating a directory
    that then blocked the retry ("already exists and is not empty"). Anything
    written here is removed again if the lock step doesn't finish.
    """
    # Only remove what this call created. `foro init <name>` guarantees an
    # empty or absent target, but scaffold_new is callable on its own and
    # must not take a user's directory with it.
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
            _PYPROJECT_TEMPLATE.format(name=fields.name, python_version=fields.python_version),
        )
        write(dir_path / "README.md", _README_TEMPLATE.format(name=fields.name))
        write(dir_path / ".gitignore", _GITIGNORE_TEMPLATE)
        write(dir_path / ".env.example", _ENV_EXAMPLE_TEMPLATE)
        write_manifest(dir_path, fields)
        written.append(dir_path / "foro.yaml")

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
    # The target pre-existed, so take back only what was written - plus the
    # two directories, which are ours and are empty again by now.
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
