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
_APP_TEMPLATE = '''from fastmcp import FastMCP

mcp = FastMCP("{name}")
'''

_SERVER_TEMPLATE = '''import foro
from app import mcp

import tools  # noqa: F401 - registers every tool in tools/ against `mcp`

if __name__ == "__main__":
    foro.run(mcp)
'''

_TOOLS_INIT_TEMPLATE = '''# Import every tool module here so `import tools` registers all of them.
# Adding a new tool: drop a file in this directory, decorate its function
# with @mcp.tool (import `mcp` from `app`), then add the import below.
from . import add  # noqa: F401
'''

_TOOL_ADD_TEMPLATE = '''from app import mcp


@mcp.tool
def add(a: int, b: int) -> int:
    return a + b
'''

_TEST_TOOLS_TEMPLATE = '''from tools.add import add


def test_add():
    assert add(2, 3) == 5
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
  and importing it in `tools/__init__.py`
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


def scaffold_new(dir_path: Path, fields: ManifestFields, git_init: bool = False) -> None:
    """Write a from-scratch project: app.py, server.py (the entrypoint -
    foro.yaml always points here), tools/, pyproject.toml, foro.yaml, a
    locked uv.lock (`uv lock`, so the golden round-trip - init's output
    must pass check - holds without a manual step), README.md, .gitignore,
    .env.example, and tests/."""
    dir_path.mkdir(parents=True, exist_ok=True)
    tools_dir = dir_path / "tools"
    tests_dir = dir_path / "tests"
    tools_dir.mkdir(parents=True, exist_ok=True)
    tests_dir.mkdir(parents=True, exist_ok=True)

    (dir_path / "app.py").write_text(_APP_TEMPLATE.format(name=fields.name))
    (dir_path / fields.entrypoint).write_text(_SERVER_TEMPLATE)
    (tools_dir / "__init__.py").write_text(_TOOLS_INIT_TEMPLATE)
    (tools_dir / "add.py").write_text(_TOOL_ADD_TEMPLATE)
    (tests_dir / "test_tools.py").write_text(_TEST_TOOLS_TEMPLATE)
    (dir_path / "pyproject.toml").write_text(
        _PYPROJECT_TEMPLATE.format(name=fields.name, python_version=fields.python_version)
    )
    (dir_path / "README.md").write_text(_README_TEMPLATE.format(name=fields.name))
    (dir_path / ".gitignore").write_text(_GITIGNORE_TEMPLATE)
    (dir_path / ".env.example").write_text(_ENV_EXAMPLE_TEMPLATE)
    write_manifest(dir_path, fields)

    subprocess.run(["uv", "lock"], cwd=dir_path, check=True, capture_output=True)
    if git_init:
        init_git_repo(dir_path)


def init_git_repo(dir_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=dir_path, check=True, capture_output=True)
