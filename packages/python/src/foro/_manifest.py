"""Port of foro-sh/platform's apps/api/src/services/manifest.ts.

Every rule here must match the platform exactly - `foro check` and the
platform's build pipeline can never be allowed to silently disagree about
what's valid. manifest-cases.json is the shared test table both sides run:
tests/test_manifest_cases.py here, and foro-sh/platform's manifest.test.ts,
which imports the same table from `@foro-sh/foro/manifest-cases` (issue #5).
A rule changed on one side without the other fails that table on both.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from pathlib import Path

import yaml as pyyaml

from foro._python_project import DEPENDENCY_MANAGERS

NAME_RE = re.compile(r"^[a-z0-9-]{3,48}$")
# Per path segment: letters, digits, dot, underscore, hyphen - no shell
# metacharacters, no whitespace, no newlines. is_valid_repo_path below applies
# this to every segment; a leading `/`, `//`, or a trailing `/` all produce an
# empty segment, which the `+` quantifier already rejects, so those don't need
# a separate check.
_PATH_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")
PYTHON_VERSIONS = ["3.11", "3.12", "3.13"]
MIN_PORT = 1024
MAX_PORT = 65535
# The platform's health sidecar always binds this port inside the container
# (foro-wrapper.sh) - a server on the same port either fails to start or is
# shadowed by it, so Traefik would route + health-check into a dead end.
# Mirrors container-spec.ts's SIDECAR_PORT.
SIDECAR_PORT = 8001

DEFAULT_PYTHON_VERSION = "3.12"
DEFAULT_PORT = 8000


class ManifestError(Exception):
    """A missing, unparseable, or invalid foro.yaml. `reason` matches the
    platform's ManifestRejectionReason (@foro/types)."""

    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass
class ValidatedManifest:
    name: str
    build_path: str
    entrypoint: str
    python_version: str
    port: int
    dependency_manager: str | None


def is_valid_repo_path(p: str) -> bool:
    """A relative path inside the repo: no `..` traversal, absolute leading
    `/`, NUL byte, or backslash, no segment starting with `-`, and every
    `/`-separated segment restricted to _PATH_SEGMENT_RE (platform issue #605
    - a bare traversal/absolute check still let shell metacharacters and
    newlines through). Nested layouts are allowed (platform issue #268, e.g.
    `src/server.py`). Used for every path-shaped field the platform
    interpolates into a Dockerfile or shell call: `manifest_path`,
    `entrypoint`, `build_path`.

    The leading-`-` rule closes what #605's segment regex left open. `-` is
    inside the allowed character class, so `--isolated` and `-rf` validated as
    paths, and a path is not always read as one: `foro dev` runs
    `uv run <entrypoint>`, where an entrypoint that starts with a dash is an
    option to uv rather than a file. Same shape wherever these land in an
    argv or a shell word. No real file is spelled this way, and one that is
    can still be reached as `./-x.py`.

    `fullmatch`, not `match`: without it, Python's `$` matches just before a
    trailing newline at the end of the string (unlike JavaScript's, which is
    strict), so `match` alone would let e.g. `"foo.py\\n"` through.
    """
    if "\0" in p or "\\" in p:
        return False
    return all(
        segment != ".." and not segment.startswith("-") and _PATH_SEGMENT_RE.fullmatch(segment)
        for segment in p.split("/")
    )


def parse_and_validate(build_dir: Path, manifest_path: str) -> ValidatedManifest:
    """Read, parse, and fully validate the foro.yaml at `manifest_path` (a
    repo-relative directory, "." for root) inside `build_dir`. Raises
    ManifestError with a message safe to surface to the user."""
    if not is_valid_repo_path(manifest_path):
        raise ManifestError(
            "manifest_path must be a relative path within the repo "
            "(no `..` traversal or shell metacharacters)",
            "invalid_build_path",
        )

    try:
        raw = (build_dir / manifest_path / "foro.yaml").read_text()
    except OSError:
        # A package.json with no foro.yaml is the TypeScript/JS funnel wall
        # (v0 only supports Python + uv) - bucket separately from a Python
        # repo that simply forgot the manifest.
        if manifest_path == "." and (build_dir / "package.json").exists():
            raise ManifestError(
                "This looks like a TypeScript/JavaScript project - foro.sh v0 only supports Python + uv",
                "unsupported_language",
            ) from None
        raise ManifestError(
            "foro.yaml not found in repo root"
            if manifest_path == "."
            else f"foro.yaml not found in {manifest_path}",
            "missing_manifest",
        ) from None

    try:
        doc = pyyaml.safe_load(raw)
    except pyyaml.YAMLError as err:
        raise ManifestError(f"foro.yaml is not valid YAML: {err}", "invalid_yaml") from None

    if not isinstance(doc, dict):
        raise ManifestError("foro.yaml must be a mapping of fields", "invalid_shape")

    # name - required
    name = doc.get("name")
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise ManifestError("foro.yaml `name` must match ^[a-z0-9-]{3,48}$", "invalid_name")

    # entrypoint - required. Relative subpaths are allowed (e.g. src/server.py).
    entrypoint = doc.get("entrypoint")
    if not isinstance(entrypoint, str) or not is_valid_repo_path(entrypoint):
        raise ManifestError(
            "foro.yaml `entrypoint` must be a relative path within the repo "
            "(no `..` traversal or shell metacharacters)",
            "invalid_entrypoint",
        )

    # build_path - optional, relative to the manifest's own directory
    # (default: the manifest dir itself). Resolved to repo-relative so every
    # downstream consumer keeps working with a single repo-relative path.
    build_path = manifest_path
    if "build_path" in doc:
        raw_build_path = doc["build_path"]
        if not isinstance(raw_build_path, str) or not is_valid_repo_path(raw_build_path):
            raise ManifestError(
                "foro.yaml `build_path` must be a relative path within the repo "
                "(no `..` traversal or shell metacharacters)",
                "invalid_build_path",
            )
        build_path = posixpath.normpath(posixpath.join(manifest_path, raw_build_path))

    # python_version - optional allowlist. Accept an unquoted YAML number too
    # (e.g. 3.12 parses as a float) by normalising to a string first.
    python_version = DEFAULT_PYTHON_VERSION
    if "python_version" in doc:
        raw_version = doc["python_version"]
        normalised = str(raw_version) if isinstance(raw_version, (int, float)) else raw_version
        if not isinstance(normalised, str) or normalised not in PYTHON_VERSIONS:
            raise ManifestError(
                f"foro.yaml `python_version` must be one of {', '.join(PYTHON_VERSIONS)}",
                "invalid_python_version",
            )
        python_version = normalised

    # port - optional, 1024-65535, excluding SIDECAR_PORT.
    port = DEFAULT_PORT
    if "port" in doc:
        raw_port = doc["port"]
        if (
            isinstance(raw_port, bool)
            or not isinstance(raw_port, int)
            or not (MIN_PORT <= raw_port <= MAX_PORT)
        ):
            raise ManifestError(
                f"foro.yaml `port` must be an integer between {MIN_PORT} and {MAX_PORT}",
                "invalid_port",
            )
        if raw_port == SIDECAR_PORT:
            raise ManifestError(
                f"foro.yaml `port` cannot be {SIDECAR_PORT} - that port is reserved for "
                "the platform's health sidecar",
                "invalid_port",
            )
        port = raw_port

    # dependency_manager - optional override for ambiguous repos.
    dependency_manager: str | None = None
    if "dependency_manager" in doc:
        raw_dm = doc["dependency_manager"]
        if not isinstance(raw_dm, str) or raw_dm not in DEPENDENCY_MANAGERS:
            raise ManifestError(
                f"foro.yaml `dependency_manager` must be one of {', '.join(DEPENDENCY_MANAGERS)}",
                "invalid_dependency_manager",
            )
        dependency_manager = raw_dm

    return ValidatedManifest(
        name=name,
        build_path=build_path,
        entrypoint=entrypoint,
        python_version=python_version,
        port=port,
        dependency_manager=dependency_manager,
    )
