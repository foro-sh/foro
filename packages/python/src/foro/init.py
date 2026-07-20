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
# an MCP server (contain the FastMCP( marker) count as a hit - mirrors the
# spirit of the platform's own detection, applied to entrypoints instead of
# dependency managers.
ENTRYPOINT_CANDIDATES = ["server.py", "main.py", "src/server.py", "app.py"]
_FASTMCP_MARKER = "FastMCP("


@dataclass
class ManifestFields:
    name: str
    entrypoint: str
    python_version: str = DEFAULT_PYTHON_VERSION
    port: int = DEFAULT_PORT
    dependency_manager: str | None = None


def detect_entrypoint_candidates(dir_path: Path) -> list[str]:
    hits = []
    for candidate in ENTRYPOINT_CANDIDATES:
        path = dir_path / candidate
        if path.is_file() and _FASTMCP_MARKER in path.read_text(errors="ignore"):
            hits.append(candidate)
    return hits


def detect_existing_dependency_manager(dir_path: Path) -> str | None:
    try:
        return detect_dependency_manager(dir_path)
    except DependencyManagerError:
        return None


def manifest_yaml(fields: ManifestFields) -> str:
    doc: dict[str, object] = {"name": fields.name, "entrypoint": fields.entrypoint}
    if fields.python_version != DEFAULT_PYTHON_VERSION:
        doc["python_version"] = fields.python_version
    if fields.port != DEFAULT_PORT:
        doc["port"] = fields.port
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


_SERVER_TEMPLATE = '''from fastmcp import FastMCP

import foro

mcp = FastMCP("{name}")


@mcp.tool
def add(a: int, b: int) -> int:
    return a + b


if __name__ == "__main__":
    foro.run(mcp)
'''

_PYPROJECT_TEMPLATE = '''[project]
name = "{name}"
version = "0.1.0"
requires-python = ">={python_version}"
dependencies = ["fastmcp", "foro"]
'''


def scaffold_new(dir_path: Path, fields: ManifestFields, git_init: bool = False) -> None:
    """Write a from-scratch project: the entrypoint file, pyproject.toml,
    foro.yaml, and a locked uv.lock (`uv lock`, so the golden round-trip -
    init's output must pass check - holds without a manual step)."""
    dir_path.mkdir(parents=True, exist_ok=True)
    entrypoint_path = dir_path / fields.entrypoint
    entrypoint_path.parent.mkdir(parents=True, exist_ok=True)
    entrypoint_path.write_text(_SERVER_TEMPLATE.format(name=fields.name))
    (dir_path / "pyproject.toml").write_text(
        _PYPROJECT_TEMPLATE.format(name=fields.name, python_version=fields.python_version)
    )
    write_manifest(dir_path, fields)
    subprocess.run(["uv", "lock"], cwd=dir_path, check=True, capture_output=True)
    if git_init:
        subprocess.run(["git", "init"], cwd=dir_path, check=True, capture_output=True)
