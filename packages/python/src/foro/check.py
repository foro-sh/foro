"""`foro check` - statically validate a repo against foro.sh's deploy
contract, so a failure surfaces instantly and locally instead of as a
60-second health-check timeout.

Layers two things on top of each other:
  1. The same foro.yaml validation the platform runs at deploy time
     (_manifest.py, _python_project.py) - same rules, same reason codes.
  2. Check-only rules the platform can't catch until build time: whether the
     entrypoint file actually exists, and whether a committed uv.lock is in
     sync with pyproject.toml.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from foro._manifest import ManifestError, parse_and_validate
from foro._node_project import NodeDependencyManagerError
from foro._node_project import detect_dependency_manager as detect_node_dependency_manager
from foro._proc import MissingToolError
from foro._proc import run as _run
from foro._python_project import DependencyManagerError, detect_dependency_manager

# Breaks the platform's metrics shim (infra/templates/sitecustomize.py),
# which only patches fastmcp.FastMCP - a warning, not a failure, since the
# server still deploys and serves tools, it just won't emit tool metrics.
_WRONG_FASTMCP_IMPORT = "from mcp.server.fastmcp import FastMCP"


@dataclass
class CheckResult:
    ok: bool
    reason: str | None = None
    message: str | None = None
    warnings: list[str] = field(default_factory=list)


def run_check(repo_dir: Path | str = ".") -> CheckResult:
    repo_dir = Path(repo_dir)

    try:
        manifest = parse_and_validate(repo_dir, ".")
    except ManifestError as err:
        return CheckResult(ok=False, reason=err.reason, message=str(err))

    build_dir = repo_dir / manifest.build_path

    entrypoint_path = build_dir / manifest.entrypoint
    if not entrypoint_path.is_file():
        return CheckResult(
            ok=False,
            reason="entrypoint_file_missing",
            message=f"entrypoint {manifest.entrypoint!r} not found under {manifest.build_path}",
        )

    detect = (
        detect_node_dependency_manager
        if manifest.runtime == "node"
        else detect_dependency_manager
    )
    try:
        manager = detect(build_dir, manifest.dependency_manager)
    except (DependencyManagerError, NodeDependencyManagerError) as err:
        return CheckResult(ok=False, reason="unsupported_project", message=str(err))

    warnings: list[str] = []
    if manager == "uv":
        lockfile = build_dir / "uv.lock"
        if not lockfile.exists():
            # Not fatal: the platform falls back to an unlocked `uv sync`
            # when uv.lock is absent (python-project.ts's
            # UV_UNLOCKED_INSTALL) - just slower and non-reproducible, not a
            # rejected deploy.
            warnings.append(
                "no uv.lock committed - builds will use a slower, non-reproducible "
                "unlocked install. Run `uv lock`."
            )
        else:
            # Only this rule needs uv, so a missing uv downgrades it to a
            # warning rather than failing a repo that is probably fine.
            try:
                in_sync = _uv_lock_in_sync(build_dir)
            except MissingToolError as err:
                warnings.append(f"{err}. uv.lock was not checked against pyproject.toml.")
                in_sync = True
            if not in_sync:
                return CheckResult(
                    ok=False,
                    reason="lockfile_out_of_sync",
                    message="uv.lock is out of sync with pyproject.toml - `uv sync --frozen` "
                    "would fail the build. Run `uv lock`.",
                )

    bad_import_file = _find_wrong_fastmcp_import(build_dir)
    if bad_import_file:
        warnings.append(
            f"{bad_import_file} imports `mcp.server.fastmcp` instead of the standalone "
            "`fastmcp` package - the platform's metrics shim won't attach, so tool metrics "
            "won't emit."
        )

    return CheckResult(ok=True, warnings=warnings)


def _uv_lock_in_sync(build_dir: Path) -> bool:
    """Raises MissingToolError when `uv` isn't installed - the caller decides
    what a check it could not run means."""
    return _run(["uv", "lock", "--check"], cwd=build_dir).returncode == 0


# Vendored or installed source carries the marker string itself (inside
# `mcp`/`fastmcp`, or a test asserting on it), and a hit there is a false
# positive, not the user's code. Any dot-directory is skipped too, which
# covers .venv, .tox, .git and whatever the next tool invents.
_SCAN_EXCLUDE_DIRS = {"__pycache__", "node_modules", "site-packages", "venv", "env", "tests"}


def _is_scannable(relative: Path) -> bool:
    return not any(
        part in _SCAN_EXCLUDE_DIRS or part.startswith(".") for part in relative.parts[:-1]
    )


def _find_wrong_fastmcp_import(build_dir: Path) -> str | None:
    """The FastMCP construction that matters doesn't have to live in the
    entrypoint file - the recommended structure (foro init's own scaffold)
    puts it in app.py instead, imported by the entrypoint. Scanning every
    .py file under build_dir (not just the entrypoint) is what keeps this
    check meaningful for that structure instead of going blind."""
    for path in sorted(build_dir.rglob("*.py")):
        if not _is_scannable(path.relative_to(build_dir)):
            continue
        try:
            text = path.read_text()
        except OSError:
            continue
        if _WRONG_FASTMCP_IMPORT in text:
            return str(path.relative_to(build_dir))
    return None
