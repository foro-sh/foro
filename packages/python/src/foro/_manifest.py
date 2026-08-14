"""Port of foro-sh/platform's apps/api/src/services/manifest.ts.

Every rule here must match the platform exactly - `foro check` and the
platform's build pipeline can never be allowed to silently disagree about
what's valid. manifest-cases.json is the shared test table both sides run:
tests/test_manifest_cases.py here, and foro-sh/platform's manifest.test.ts,
which imports the same table from `@foro-sh/foro/manifest-cases` (issue #5).
A rule changed on one side without the other fails that table on both.

There is no `foro.yaml` (issue #76). A project's config is read from the file
it already has - `pyproject.toml` for Python, `package.json` for Node - and
the few values neither declares live in an optional `[tool.foro]` table or
`"foro"` key. The common case declares nothing foro-specific at all.
"""

from __future__ import annotations

import json
import posixpath
import re
from dataclasses import dataclass
from pathlib import Path

try:  # 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - 3.10 only
    import tomli as tomllib  # type: ignore[no-redef]

from foro._node_project import DEPENDENCY_MANAGERS as NODE_DEPENDENCY_MANAGERS
from foro._python_project import DEPENDENCY_MANAGERS as PYTHON_DEPENDENCY_MANAGERS

NAME_RE = re.compile(r"^[a-z0-9-]{3,48}$")
# Per path segment: letters, digits, dot, underscore, hyphen - no shell
# metacharacters, no whitespace, no newlines. is_valid_repo_path below applies
# this to every segment; a leading `/`, `//`, or a trailing `/` all produce an
# empty segment, which the `+` quantifier already rejects, so those don't need
# a separate check.
_PATH_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")
# Interpreter allowlist per runtime, and the single source of truth for which
# runtimes exist at all (platform issue #715). A runtime reaches this table
# only once the platform can build it, gate it, and health-check it end to
# end - the entry is what makes it selectable.
#
# Node starts at 22, not 20: the platform's in-container gate runs on the
# user's own base image there and ships as TypeScript, which node only strips
# unflagged from 22.18.
RUNTIME_VERSIONS: dict[str, list[str]] = {
    "python": ["3.11", "3.12", "3.13"],
    "node": ["22", "24"],
}
DEFAULT_RUNTIME_VERSIONS: dict[str, str] = {
    "python": "3.12",
    "node": "24",
}
# Derived so it can't drift from the table it is validated against.
RUNTIMES = list(RUNTIME_VERSIONS)
# The `dependency_manager` allowlist a runtime is validated against - each
# detector's own enum, so the two can't drift apart.
DEPENDENCY_MANAGERS_BY_RUNTIME: dict[str, list[str]] = {
    "python": PYTHON_DEPENDENCY_MANAGERS,
    "node": NODE_DEPENDENCY_MANAGERS,
}
MIN_PORT = 1024
MAX_PORT = 65535
# Ports the platform's gate binds inside every container (foro-proxy.mts): the
# one Traefik routes to, and the one it health-checks. A server on either
# fails to start or is shadowed by the gate, so Traefik would route or
# health-check into a dead end. Mirrors container-spec.ts.
SIDECAR_PORT = 8001
PROXY_PORT = 8002
RESERVED_PORTS = sorted([PROXY_PORT, SIDECAR_PORT])

DEFAULT_RUNTIME = "python"
DEFAULT_PORT = 8000

# The config file each runtime is read from. Presence is also what decides the
# runtime, so this table is the whole "which language is this" rule.
CONFIG_FILES: dict[str, str] = {
    "python": "pyproject.toml",
    "node": "package.json",
}

# Every key the foro block may carry. Anything else is a hard rejection: a key
# the platform doesn't read is almost always a typo or a stale name, and
# silently dropping it changes what the server runs on without saying so.
# `name` is deliberately absent - it is display-only and always comes from the
# package's own name field.
KNOWN_FIELDS = {
    "build_path",
    "entrypoint",
    "runtime",
    "runtime_version",
    "port",
    "dependency_manager",
}

# Checked in order; the first that exists wins. Mirrors the platform's own
# list - a server whose entry file is spelled some other way says so in
# `entrypoint`.
PYTHON_ENTRYPOINT_CANDIDATES = ["server.py", "main.py", "src/server.py", "app.py"]

# Fallback display name. `name` never fails validation - it is shown in the
# dashboard and nothing else (the slug is generated), so an unusable package
# name is normalised or replaced rather than rejected.
FALLBACK_NAME = "mcp-server"


class ManifestError(Exception):
    """A missing, unparseable, or invalid project config. `reason` matches the
    platform's ManifestRejectionReason (@foro/types)."""

    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass
class ValidatedManifest:
    name: str
    build_path: str
    entrypoint: str
    runtime: str
    runtime_version: str
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

    The leading-`-` rule closes what #605 left open: `-` is inside the
    allowed class, so `--isolated` validated as a path and then read as an
    option to `uv run`. A real file spelled that way is still `./-x.py`.

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


def display_name(raw: object) -> str:
    """A package name spelled as a foro display name. Scoped npm names, dots,
    underscores and capitals are all legal in the ecosystems we read from and
    none of them match NAME_RE, so normalise rather than reject."""
    normalised = re.sub(r"^@[^/]+/", "", raw if isinstance(raw, str) else "")
    normalised = re.sub(r"[^a-z0-9]+", "-", normalised.lower()).strip("-")[:48].rstrip("-")
    return normalised if NAME_RE.fullmatch(normalised) else FALLBACK_NAME


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def _compare(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    """Compare two version keys on the components they share, so `3.11.2`
    bounds `3.11` and `22` bounds `22.4.1` without either side needing a
    component the other doesn't have."""
    n = min(len(a), len(b))
    return (a[:n] > b[:n]) - (a[:n] < b[:n])


_SPEC_CLAUSE_RE = re.compile(r"(>=|<=|==|!=|~=|~|\^|>|<)?\s*(\d+(?:\.\d+)*)")


def _clause_bounds(
    operator: str, key: tuple[int, ...]
) -> tuple[tuple[int, ...] | None, tuple[int, ...] | None, bool]:
    """(lower, upper, upper_is_inclusive) for one clause of a version spec.

    `~` and `~=` are read with PEP 440's meaning (bump the second-to-last
    component); npm's `~22.1` is narrower than that, but both allowlists are
    coarse enough - majors for node, major.minor for python - that the
    difference can't select a different entry.
    """
    if operator in (">=", ">"):
        return key, None, False
    if operator in ("==", ""):
        return key, key, True
    if operator == "^":
        return key, (key[0] + 1,), False
    if operator in ("~=", "~"):
        head = key[:-1] if len(key) > 1 else key
        return key, head[:-1] + (head[-1] + 1,), False
    if operator == "<=":
        return None, key, True
    return None, key, False  # `<`


def resolve_runtime_version(spec: object, runtime: str) -> str:
    """The interpreter version a `requires-python` / `engines.node` range asks
    for: the newest allowlisted version inside it.

    Deliberately shallow - it reads the operators it recognises and ignores
    everything else PEP 440 and npm allow (environment markers, `||`, `*`). A
    spec it can't read at all resolves to the default rather than guessing; a
    spec it *can* read that excludes every allowlisted version is an error,
    because silently running an interpreter the project says it doesn't
    support is worse than a failed deploy.
    """
    versions = RUNTIME_VERSIONS[runtime]
    if not isinstance(spec, str) or not spec.strip():
        return DEFAULT_RUNTIME_VERSIONS[runtime]

    lower: tuple[int, ...] | None = None
    upper: tuple[int, ...] | None = None
    upper_inclusive = True
    recognised = False

    for operator, raw_version in _SPEC_CLAUSE_RE.findall(spec):
        clause_lower, clause_upper, inclusive = _clause_bounds(operator, _version_key(raw_version))
        recognised = True
        if clause_lower is not None and (lower is None or _compare(clause_lower, lower) > 0):
            lower = clause_lower
        if clause_upper is not None and (upper is None or _compare(clause_upper, upper) < 0):
            upper, upper_inclusive = clause_upper, inclusive

    if not recognised:
        return DEFAULT_RUNTIME_VERSIONS[runtime]

    def satisfies(version: str) -> bool:
        key = _version_key(version)
        if lower is not None and _compare(key, lower) < 0:
            return False
        if upper is not None:
            order = _compare(key, upper)
            if order > 0 or (order == 0 and not upper_inclusive):
                return False
        return True

    allowed = [version for version in versions if satisfies(version)]
    if not allowed:
        raise ManifestError(
            f"`{spec}` allows no {runtime} version foro can run - "
            f"supported: {', '.join(versions)}",
            "invalid_runtime_version",
        )
    return max(allowed, key=_version_key)


def _read_config(directory: Path) -> tuple[str, dict]:
    """The runtime and parsed config file for a project directory."""
    present = [
        runtime for runtime, filename in CONFIG_FILES.items() if (directory / filename).exists()
    ]

    if len(present) > 1:
        raise ManifestError(
            "This directory has both a pyproject.toml and a package.json - "
            "set `runtime` in the config file of the one that is the MCP server",
            "invalid_runtime",
        )
    if not present:
        extra = (
            " foro.yaml is no longer read: move its fields into a `[tool.foro]` table."
            if (directory / "foro.yaml").exists()
            else ""
        )
        raise ManifestError(
            f"No pyproject.toml or package.json found.{extra}",
            "missing_manifest",
        )

    runtime = present[0]
    path = directory / CONFIG_FILES[runtime]
    try:
        if runtime == "python":
            doc = tomllib.loads(path.read_text())
        else:
            doc = json.loads(path.read_text())
    except (tomllib.TOMLDecodeError, json.JSONDecodeError) as err:
        raise ManifestError(f"{CONFIG_FILES[runtime]} is not valid: {err}", "invalid_shape") from None

    if not isinstance(doc, dict):
        raise ManifestError(
            f"{CONFIG_FILES[runtime]} must be a mapping of fields", "invalid_shape"
        )
    return runtime, doc


def _table(doc: dict, *path: str) -> dict:
    """A nested table, or an empty one - a file is free to spell `tool` or
    `engines` as something that isn't a table, and that is not this module's
    error to raise."""
    for key in path:
        doc = doc.get(key) if isinstance(doc, dict) else None
        if not isinstance(doc, dict):
            return {}
    return doc


def _foro_block(doc: dict, runtime: str) -> dict:
    """The optional foro block, with its keys checked. Everything in it is an
    override for something the surrounding file can't say."""
    block = _table(doc, "tool").get("foro") if runtime == "python" else doc.get("foro")
    if block is None:
        return {}
    if not isinstance(block, dict):
        where = "[tool.foro]" if runtime == "python" else "`foro`"
        raise ManifestError(f"{where} must be a table of fields", "invalid_shape")

    unknown = [key for key in block if key not in KNOWN_FIELDS]
    if unknown:
        plural = "s" if len(unknown) > 1 else ""
        names = ", ".join(f"`{key}`" for key in unknown)
        raise ManifestError(
            f"foro config has unknown field{plural} {names} - "
            f"valid fields are {', '.join(sorted(KNOWN_FIELDS))}",
            "unknown_field",
        )
    return block


def _declared_name(doc: dict, runtime: str) -> object:
    if runtime == "node":
        return doc.get("name")
    # A poetry-only project has no [project] table at all.
    return _table(doc, "project").get("name") or _table(doc, "tool", "poetry").get("name")


def _declared_version_spec(doc: dict, runtime: str) -> object:
    if runtime == "node":
        return _table(doc, "engines").get("node")
    return _table(doc, "project").get("requires-python") or _table(
        doc, "tool", "poetry", "dependencies"
    ).get("python")


def _entrypoint(doc: dict, runtime: str, directory: Path) -> str:
    """The file that starts the server, in the order each ecosystem resolves
    it. Nothing here is guessed from source contents - a server that keeps its
    entry somewhere unusual sets `entrypoint` explicitly."""
    if runtime == "node":
        found: str | None = doc["main"] if isinstance(doc.get("main"), str) else None
        if found is None:
            binaries = doc.get("bin")
            if isinstance(binaries, str):
                found = binaries
            elif isinstance(binaries, dict):
                found = next(
                    (value for value in binaries.values() if isinstance(value, str)), None
                )
        if found is None and (directory / "index.js").exists():
            found = "index.js"
        if found is None:
            raise ManifestError(
                "package.json declares no usable `main` - point it at the file that "
                "starts your server, or set `entrypoint` in its `foro` key",
                "invalid_entrypoint",
            )
    else:
        found = next(
            (name for name in PYTHON_ENTRYPOINT_CANDIDATES if (directory / name).exists()), None
        )
        if found is None:
            raise ManifestError(
                "No server entry file found (looked for "
                f"{', '.join(PYTHON_ENTRYPOINT_CANDIDATES)}) - "
                "set `entrypoint` in pyproject.toml's [tool.foro] table",
                "invalid_entrypoint",
            )
    return found


def parse_and_validate(build_dir: Path, manifest_path: str) -> ValidatedManifest:
    """Read, parse, and fully validate the project config in `manifest_path`
    (a repo-relative directory, "." for root) inside `build_dir`. Raises
    ManifestError with a message safe to surface to the user."""
    if not is_valid_repo_path(manifest_path):
        raise ManifestError(
            "manifest_path must be a relative path within the repo "
            "(no `..` traversal or shell metacharacters)",
            "invalid_build_path",
        )

    directory = build_dir / manifest_path
    runtime, doc = _read_config(directory)
    block = _foro_block(doc, runtime)

    # runtime - only ever set to break a tie the file itself can't; it has to
    # agree with the file it was read from.
    if "runtime" in block:
        declared = block["runtime"]
        if declared not in RUNTIMES:
            raise ManifestError(
                f"`runtime` must be one of {', '.join(RUNTIMES)}", "invalid_runtime"
            )
        if declared != runtime:
            raise ManifestError(
                f"`runtime` is `{declared}` but this config was read from "
                f"{CONFIG_FILES[runtime]}",
                "invalid_runtime",
            )

    # entrypoint - relative subpaths are allowed (e.g. src/server.py).
    entrypoint = block["entrypoint"] if "entrypoint" in block else _entrypoint(doc, runtime, directory)
    if not isinstance(entrypoint, str) or not is_valid_repo_path(entrypoint):
        raise ManifestError(
            "`entrypoint` must be a relative path within the repo "
            "(no `..` traversal or shell metacharacters)",
            "invalid_entrypoint",
        )

    # build_path - optional, relative to the config file's own directory
    # (default: that directory). Resolved to repo-relative so every downstream
    # consumer keeps working with a single repo-relative path.
    build_path = manifest_path
    if "build_path" in block:
        raw_build_path = block["build_path"]
        if not isinstance(raw_build_path, str) or not is_valid_repo_path(raw_build_path):
            raise ManifestError(
                "`build_path` must be a relative path within the repo "
                "(no `..` traversal or shell metacharacters)",
                "invalid_build_path",
            )
        build_path = posixpath.normpath(posixpath.join(manifest_path, raw_build_path))

    # runtime_version - an explicit pin is checked against the allowlist; a
    # range in requires-python / engines.node resolves to the newest version
    # inside it.
    versions = RUNTIME_VERSIONS[runtime]
    if "runtime_version" in block:
        raw_version = block["runtime_version"]
        normalised = str(raw_version) if isinstance(raw_version, (int, float)) else raw_version
        if not isinstance(normalised, str) or normalised not in versions:
            raise ManifestError(
                f"`runtime_version` must be one of {', '.join(versions)} "
                f"for runtime `{runtime}`",
                "invalid_runtime_version",
            )
        runtime_version = normalised
    else:
        runtime_version = resolve_runtime_version(_declared_version_spec(doc, runtime), runtime)

    # port - optional, 1024-65535, excluding the gate's own ports. Servers that
    # read $PORT (which the platform injects) never set this.
    port = DEFAULT_PORT
    if "port" in block:
        raw_port = block["port"]
        if (
            isinstance(raw_port, bool)
            or not isinstance(raw_port, int)
            or not (MIN_PORT <= raw_port <= MAX_PORT)
        ):
            raise ManifestError(
                f"`port` must be an integer between {MIN_PORT} and {MAX_PORT}",
                "invalid_port",
            )
        if raw_port in RESERVED_PORTS:
            raise ManifestError(
                f"`port` cannot be {raw_port} - "
                f"{' and '.join(str(p) for p in RESERVED_PORTS)} are reserved for the "
                "platform gate",
                "invalid_port",
            )
        port = raw_port

    # dependency_manager - optional override for ambiguous repos. Allowlisted
    # per runtime: the field is shared but the vocabularies are disjoint.
    managers = DEPENDENCY_MANAGERS_BY_RUNTIME[runtime]
    dependency_manager: str | None = None
    if "dependency_manager" in block:
        raw_dm = block["dependency_manager"]
        if not isinstance(raw_dm, str) or raw_dm not in managers:
            raise ManifestError(
                f"`dependency_manager` must be one of {', '.join(managers)} "
                f"for runtime `{runtime}`",
                "invalid_dependency_manager",
            )
        dependency_manager = raw_dm

    return ValidatedManifest(
        name=display_name(_declared_name(doc, runtime)),
        build_path=build_path,
        entrypoint=entrypoint,
        runtime=runtime,
        runtime_version=runtime_version,
        port=port,
        dependency_manager=dependency_manager,
    )
