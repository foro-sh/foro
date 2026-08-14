"""Port of foro-sh/platform's apps/api/src/services/node-project.ts.

Only the detection logic - not the install/run command tables, which
foro check has no use for; it only needs to know which manager applies and
whether the matching lockfile is on disk.
"""

from __future__ import annotations

from pathlib import Path

DEPENDENCY_MANAGERS = ["npm", "pnpm", "yarn"]

LOCKFILES = {
    "npm": "package-lock.json",
    "pnpm": "pnpm-lock.yaml",
    "yarn": "yarn.lock",
}


class NodeDependencyManagerError(Exception):
    """No recognised Node project structure and no `dependency_manager` override."""


def detect_dependency_manager(build_dir: Path, override: str | None = None) -> str:
    if override:
        return override

    def has(name: str) -> bool:
        return (build_dir / name).exists()

    if has("pnpm-lock.yaml"):
        return "pnpm"
    if has("yarn.lock"):
        return "yarn"
    if has("package-lock.json"):
        return "npm"

    # Bun is deliberately absent from the enum: the platform's node base image
    # has no bun binary, and treating bun.lock as npm would install a different
    # tree than it pins. Detected only to fail with the real reason.
    if has("bun.lock") or has("bun.lockb"):
        raise NodeDependencyManagerError(
            "Bun projects are not supported yet - remove bun.lock and commit an "
            "npm, pnpm, or yarn lockfile instead"
        )

    if has("package.json"):
        return "npm"

    raise NodeDependencyManagerError(
        "No recognised Node project (expected an npm/pnpm/yarn lockfile or a package.json)"
    )
