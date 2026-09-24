"""Port of foro-sh/platform's apps/api/src/services/manifest.ts.

Shared cases: manifest-cases.json. Config is pyproject.toml or package.json.
"""

from __future__ import annotations

import ipaddress
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
_PATH_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")
# Node starts at 22: the in-container gate is TypeScript, stripped unflagged
# from 22.18.
RUNTIME_VERSIONS: dict[str, list[str]] = {
    "python": ["3.11", "3.12", "3.13"],
    "node": ["22", "24"],
}
DEFAULT_RUNTIME_VERSIONS: dict[str, str] = {
    "python": "3.12",
    "node": "24",
}
RUNTIMES = list(RUNTIME_VERSIONS)
DEPENDENCY_MANAGERS_BY_RUNTIME: dict[str, list[str]] = {
    "python": PYTHON_DEPENDENCY_MANAGERS,
    "node": NODE_DEPENDENCY_MANAGERS,
}
MIN_PORT = 1024
MAX_PORT = 65535
# foro-proxy.mts binds these inside every container.
SIDECAR_PORT = 8001
PROXY_PORT = 8002
RESERVED_PORTS = sorted([PROXY_PORT, SIDECAR_PORT])

DEFAULT_RUNTIME = "python"
DEFAULT_PORT = 8000

_IPV4_OCTET = r"(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])"
_IPV4_RE_SRC = rf"{_IPV4_OCTET}(?:\.{_IPV4_OCTET}){{3}}"
_IPV4_CIDR_RE_SRC = rf"{_IPV4_RE_SRC}/(?:[0-9]|[12][0-9]|3[0-2])"
_HOSTNAME_RE_SRC = (
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*"
)
_EGRESS_ENTRY_RE = re.compile(
    rf"^({_IPV4_CIDR_RE_SRC}|{_IPV4_RE_SRC}|{_HOSTNAME_RE_SRC}):([0-9]{{1,5}})$"
)
_IPV4_OR_CIDR_RE = re.compile(rf"^(?:{_IPV4_CIDR_RE_SRC}|{_IPV4_RE_SRC})$")
_DENIED_EGRESS_PORTS = {25, 465, 587}
_MAX_HOSTNAME_LENGTH = 253
MAX_EGRESS_ENTRIES = 20

# 10.0.0.0/8 and 192.168.0.0/16 are omitted; they stay allowlistable.
_DENIED_EGRESS_RANGES = [
    ipaddress.ip_network(cidr)
    for cidr in (
        "0.0.0.0/8",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/13",
        "172.24.0.0/14",
        "172.28.0.0/15",
        "172.31.0.0/16",
        "224.0.0.0/4",
        "240.0.0.0/4",
    )
]

CONFIG_FILES: dict[str, str] = {
    "python": "pyproject.toml",
    "node": "package.json",
}

# `name` is not a foro field; it comes from the package name.
KNOWN_FIELDS = {
    "build_path",
    "entrypoint",
    "runtime",
    "runtime_version",
    "port",
    "dependency_manager",
    "egress",
}

PYTHON_ENTRYPOINT_CANDIDATES = ["server.py", "main.py", "src/server.py", "app.py"]
FALLBACK_NAME = "mcp-server"


class ManifestError(Exception):
    """Invalid project config. `reason` matches ManifestRejectionReason."""

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
    egress: list[str] | None


def is_valid_repo_path(p: str) -> bool:
    """Relative path: no `..`, leading `/`, NUL, backslash, or segment
    starting with `-`. `fullmatch` is required: Python `$` matches before a
    trailing newline, so `match` would accept `"foo.py\\n"`."""
    if "\0" in p or "\\" in p:
        return False
    return all(
        segment != ".." and not segment.startswith("-") and _PATH_SEGMENT_RE.fullmatch(segment)
        for segment in p.split("/")
    )


def egress_entry_error(entry: str) -> str | None:
    """Rejection reason, or None. `ipaddress` with strict=False masks host
    bits; `.overlaps()` is overlap, not prefix equality."""
    match = _EGRESS_ENTRY_RE.fullmatch(entry)
    if not match:
        return (
            "must be `<destination>:<port>`, where destination is an IPv4 "
            "address, an IPv4 CIDR, or a hostname, and port is 1-65535"
        )
    port = int(match.group(2))
    if not (1 <= port <= MAX_PORT):
        return f"port must be 1-{MAX_PORT}"
    if port in _DENIED_EGRESS_PORTS:
        return f"port {port} is outbound mail, which the platform blocks for every project"
    destination = match.group(1)
    if not _IPV4_OR_CIDR_RE.fullmatch(destination):
        if len(destination) > _MAX_HOSTNAME_LENGTH:
            return f"hostname is longer than {_MAX_HOSTNAME_LENGTH} characters"
        return None
    network = ipaddress.ip_network(destination, strict=False)
    denied = next((r for r in _DENIED_EGRESS_RANGES if network.overlaps(r)), None)
    if denied is None:
        return None
    return (
        f"overlaps {denied}, which is reserved "
        "(link-local/metadata, loopback or a platform network)"
    )


def display_name(raw: object) -> str:
    """Normalise a package name to NAME_RE, or FALLBACK_NAME."""
    normalised = re.sub(r"^@[^/]+/", "", raw if isinstance(raw, str) else "")
    normalised = re.sub(r"[^a-z0-9]+", "-", normalised.lower()).strip("-")[:48].rstrip("-")
    return normalised if NAME_RE.fullmatch(normalised) else FALLBACK_NAME


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def _compare(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    """Compare on shared components so `3.11.2` bounds `3.11`."""
    n = min(len(a), len(b))
    return (a[:n] > b[:n]) - (a[:n] < b[:n])


_SPEC_CLAUSE_RE = re.compile(r"(>=|<=|==|!=|~=|~|\^|>|<)?\s*(\d+(?:\.\d+)*)")


def _clause_bounds(
    operator: str, key: tuple[int, ...]
) -> tuple[tuple[int, ...] | None, tuple[int, ...] | None, bool]:
    """(lower, upper, upper_is_inclusive). `~` / `~=` follow PEP 440."""
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


def _branch_allowed(branch: str, versions: list[str]) -> tuple[list[str], bool]:
    """Allowlisted versions one `||`-free branch admits, plus whether any
    operator was recognised. `!=3.11.2` excludes all of 3.11."""
    lower: tuple[int, ...] | None = None
    upper: tuple[int, ...] | None = None
    upper_inclusive = True
    excluded: list[tuple[int, ...]] = []
    recognised = False

    for operator, raw_version in _SPEC_CLAUSE_RE.findall(branch):
        key = _version_key(raw_version)
        recognised = True
        if operator == "!=":
            excluded.append(key)
            continue
        clause_lower, clause_upper, inclusive = _clause_bounds(operator, key)
        if clause_lower is not None and (lower is None or _compare(clause_lower, lower) > 0):
            lower = clause_lower
        if clause_upper is not None and (upper is None or _compare(clause_upper, upper) < 0):
            upper, upper_inclusive = clause_upper, inclusive

    def satisfies(version: str) -> bool:
        key = _version_key(version)
        if lower is not None and _compare(key, lower) < 0:
            return False
        if upper is not None:
            order = _compare(key, upper)
            if order > 0 or (order == 0 and not upper_inclusive):
                return False
        return not any(_compare(key, exclusion) == 0 for exclusion in excluded)

    return [version for version in versions if satisfies(version)], recognised


def resolve_runtime_version(spec: object, runtime: str) -> str:
    """Newest allowlisted version inside a `requires-python` / `engines.node`
    range. Unreadable specs use the default. `||` is a union, not an
    intersection: `^22 || ^24` must not resolve to empty."""
    versions = RUNTIME_VERSIONS[runtime]
    if not isinstance(spec, str) or not spec.strip():
        return DEFAULT_RUNTIME_VERSIONS[runtime]

    allowed: set[str] = set()
    recognised = False
    for branch in spec.split("||"):
        branch_allowed, branch_recognised = _branch_allowed(branch, versions)
        allowed.update(branch_allowed)
        recognised = recognised or branch_recognised

    if not recognised:
        return DEFAULT_RUNTIME_VERSIONS[runtime]
    if not allowed:
        raise ManifestError(
            f"`{spec}` allows no {runtime} version foro can run - "
            f"supported: {', '.join(versions)}",
            "invalid_runtime_version",
        )
    return max(allowed, key=_version_key)


def _parse_config(directory: Path, runtime: str) -> dict:
    path = directory / CONFIG_FILES[runtime]
    try:
        if runtime == "python":
            doc = tomllib.loads(path.read_text())
        else:
            doc = json.loads(path.read_text())
    except (tomllib.TOMLDecodeError, json.JSONDecodeError, UnicodeDecodeError) as err:
        raise ManifestError(
            f"{CONFIG_FILES[runtime]} is not valid: {err}", "invalid_shape"
        ) from None

    if not isinstance(doc, dict):
        raise ManifestError(f"{CONFIG_FILES[runtime]} must be a mapping of fields", "invalid_shape")
    return doc


def _read_config(directory: Path) -> tuple[str, dict]:
    """The runtime and parsed config file for a project directory."""
    present = [
        runtime for runtime, filename in CONFIG_FILES.items() if (directory / filename).exists()
    ]

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
    if len(present) == 1:
        return present[0], _parse_config(directory, present[0])

    parsed = {runtime: _parse_config(directory, runtime) for runtime in present}
    claimed = [
        runtime
        for runtime, doc in parsed.items()
        if _foro_block(doc, runtime).get("runtime") == runtime
    ]
    if len(claimed) != 1:
        raise ManifestError(
            "This directory has both a pyproject.toml and a package.json - set "
            "`runtime` in the `[tool.foro]` table or `foro` key of whichever one "
            "is the MCP server, and only that one",
            "invalid_runtime",
        )
    return claimed[0], parsed[claimed[0]]


def _table(doc: dict, *path: str) -> dict:
    """Nested table, or {} if a key is missing or not a table."""
    for key in path:
        doc = doc.get(key) if isinstance(doc, dict) else None
        if not isinstance(doc, dict):
            return {}
    return doc


def _foro_block(doc: dict, runtime: str) -> dict:
    """Optional foro block; unknown keys are rejected."""
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
    return _table(doc, "project").get("name") or _table(doc, "tool", "poetry").get("name")


def _declared_version_spec(doc: dict, runtime: str) -> object:
    if runtime == "node":
        return _table(doc, "engines").get("node")
    return _table(doc, "project").get("requires-python") or _table(
        doc, "tool", "poetry", "dependencies"
    ).get("python")


def _entrypoint(doc: dict, runtime: str, directory: Path) -> str:
    """Resolved entry file. Unusual locations must set `entrypoint`."""
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
    """Validate the project config in `manifest_path` (`.` for repo root)."""
    if not is_valid_repo_path(manifest_path):
        raise ManifestError(
            "manifest_path must be a relative path within the repo "
            "(no `..` traversal or shell metacharacters)",
            "invalid_build_path",
        )

    directory = build_dir / manifest_path
    runtime, doc = _read_config(directory)
    block = _foro_block(doc, runtime)

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

    entrypoint = block["entrypoint"] if "entrypoint" in block else _entrypoint(doc, runtime, directory)
    if not isinstance(entrypoint, str) or not is_valid_repo_path(entrypoint):
        raise ManifestError(
            "`entrypoint` must be a relative path within the repo "
            "(no `..` traversal or shell metacharacters)",
            "invalid_entrypoint",
        )

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

    # Absent egress is None (permissive). Present empty list is deny-all.
    # Do not test this field for truthiness.
    egress: list[str] | None = None
    if "egress" in block:
        raw_egress = block["egress"]
        if not isinstance(raw_egress, list):
            raise ManifestError("`egress` must be an array of strings", "invalid_egress")
        if len(raw_egress) > MAX_EGRESS_ENTRIES:
            raise ManifestError(
                f"`egress` allows at most {MAX_EGRESS_ENTRIES} entries", "invalid_egress"
            )
        for raw_entry in raw_egress:
            problem = (
                egress_entry_error(raw_entry)
                if isinstance(raw_entry, str)
                else "must be `<destination>:<port>`, written as a string"
            )
            if problem:
                raise ManifestError(f"`egress` entry `{raw_entry}` {problem}", "invalid_egress")
        egress = list(raw_egress)

    return ValidatedManifest(
        name=display_name(_declared_name(doc, runtime)),
        build_path=build_path,
        entrypoint=entrypoint,
        runtime=runtime,
        runtime_version=runtime_version,
        port=port,
        dependency_manager=dependency_manager,
        egress=egress,
    )
