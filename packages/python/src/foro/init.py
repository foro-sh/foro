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
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml as pyyaml

from foro._manifest import DEFAULT_PORT, DEFAULT_PYTHON_VERSION
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

```bash
uvx foro auth login   # once per machine
uvx foro deploy
```

`foro deploy` packages this directory, ships it, and streams the build until
it's live at a generated `https://<slug>.foro.sh` URL.
'''

# Scaffolded so an agent working in this repo has the deploy contract even
# without a foro plugin installed - which is most agents. Deliberately the
# contract and its footguns only, not a tutorial: everything here is something
# that fails a deploy or fails it late, and nothing here is discoverable by
# reading the generated code.
_AGENTS_TEMPLATE = '''# Agent instructions

This is a [foro.sh](https://foro.sh) MCP server: a Python FastMCP server that
deploys to a public URL. The rules below are the platform's deploy contract.
Breaking one usually fails *late* - a green build, then a 60-second health-check
timeout with no obvious cause.

## Serving

- **Start the server with `foro.run(mcp)`, never `mcp.run()`.** A bare
  `mcp.run()` serves stdio, which never opens a port, and the platform starts
  the container and probes a TCP port. Nothing looks wrong with the tools; the
  server just never listens.
- **Never hardcode a host or port.** `foro.run()` binds `0.0.0.0:$MCP_PORT`,
  which is what the health check probes. `127.0.0.1` or a fixed port that
  disagrees with `foro.yaml` fails in a way that reads like a crash.
- `server.py` is the entrypoint `foro.yaml` points at. If you rename it, update
  `foro.yaml`'s `entrypoint` in the same change.

## Tools

- One tool per file in `tools/`, each doing `from app import mcp` and decorating
  its function with `@mcp.tool`.
- **Add every new tool module to the imports in `tools/__init__.py`.** A file in
  `tools/` that isn't imported there registers nothing, and the symptom is an
  empty tool list on a server that otherwise looks healthy.
- Type the parameters and describe the tool - a calling model picks on the
  description, and the whole tool list is resent on every request whether it's
  called or not.

## Secrets

- Read them with `foro.secret("NAME")`, which raises an error naming where to
  set it. Never `os.environ[...]` with a silent default.
- Real values go in the project's Secrets tab on the foro.sh dashboard and
  arrive as environment variables at deploy time. `.env` is for local runs only
  (`foro dev` loads it) and is never committed or deployed.

## Before every deploy

```bash
uvx foro check    # manifest, entrypoint, lockfile - the platform's own rules
uvx foro dev      # runs it as the platform will, and probes the port
```

`foro check` mirrors the platform's validation rule for rule. `foro dev` is what
catches the serving mistakes above, in seconds instead of in the cloud a minute
later. Don't report the server as working off a banner - hit the `/mcp` path it
prints and confirm a real `tools/list` naming the tools you built.

Commit the lockfile. One that is *out of sync* with `pyproject.toml` is worse
than none: the build installs `--frozen` and fails outright.

## Deploying

`uvx foro deploy` packages this directory and streams the build. It needs a
one-time `uvx foro auth login`, which requires a human to approve a code in a
browser - that step cannot be automated.

The deployed URL is a **generated, immutable slug** (`https://<slug>.foro.sh`).
`name` in `foro.yaml` is a display name and has no effect on the URL.
'''

_GITIGNORE_TEMPLATE = '''.venv/
__pycache__/
*.pyc
.env
.pytest_cache/
.DS_Store
# Which foro.sh project this directory deploys to - local, and per-clone.
.foro/
'''

_ENV_EXAMPLE_TEMPLATE = '''# Copy to .env for local development - foro dev loads it automatically.
# Never commit the real .env; in production these are set as Secrets in
# the foro.sh dashboard instead, and read the same way via foro.secret().
#
# EXAMPLE_API_KEY=
'''


def scaffold_new(dir_path: Path, fields: ManifestFields, git_init: bool = False) -> None:
    """Write a from-scratch project: app.py, server.py (the entrypoint -
    foro.yaml always points here), tools/, pyproject.toml, foro.yaml, a
    locked uv.lock (`uv lock`, so the golden round-trip - init's output
    must pass check - holds without a manual step), README.md, AGENTS.md,
    .gitignore, .env.example, and tests/."""
    dir_path.mkdir(parents=True, exist_ok=True)
    tools_dir = dir_path / "tools"
    tests_dir = dir_path / "tests"
    tools_dir.mkdir(parents=True, exist_ok=True)
    tests_dir.mkdir(parents=True, exist_ok=True)

    (dir_path / "app.py").write_text(_APP_TEMPLATE.format(name=fields.name))
    (dir_path / fields.entrypoint).write_text(_SERVER_TEMPLATE)
    (tools_dir / "__init__.py").write_text(_TOOLS_INIT_TEMPLATE)
    (tools_dir / "add.py").write_text(_TOOL_ADD_TEMPLATE)
    (tests_dir / "test_tools.py").write_text(
        _TEST_TOOLS_TEMPLATE.replace("__ENTRYPOINT__", Path(fields.entrypoint).stem)
    )
    (dir_path / "pyproject.toml").write_text(
        _PYPROJECT_TEMPLATE.format(name=fields.name, python_version=fields.python_version)
    )
    (dir_path / "README.md").write_text(_README_TEMPLATE.format(name=fields.name))
    (dir_path / "AGENTS.md").write_text(_AGENTS_TEMPLATE)
    (dir_path / ".gitignore").write_text(_GITIGNORE_TEMPLATE)
    (dir_path / ".env.example").write_text(_ENV_EXAMPLE_TEMPLATE)
    write_manifest(dir_path, fields)

    subprocess.run(["uv", "lock"], cwd=dir_path, check=True, capture_output=True)
    if git_init:
        init_git_repo(dir_path)


def init_git_repo(dir_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=dir_path, check=True, capture_output=True)
