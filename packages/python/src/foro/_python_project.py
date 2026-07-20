"""Port of foro-sh/platform's apps/api/src/services/python-project.ts.

Only the detection logic - not the install/run command tables, which
foro check has no use for; it only needs to know which manager applies and
whether the matching lockfile is on disk.
"""

from __future__ import annotations

from pathlib import Path

DEPENDENCY_MANAGERS = ["uv", "pdm", "poetry", "pipenv", "uv-pip"]

LOCKFILES = {
    "uv": "uv.lock",
    "pdm": "pdm.lock",
    "poetry": "poetry.lock",
    "pipenv": "Pipfile.lock",
}


class DependencyManagerError(Exception):
    """No recognised Python project structure and no `dependency_manager` override."""


def detect_dependency_manager(build_dir: Path, override: str | None = None) -> str:
    if override:
        return override

    def has(name: str) -> bool:
        return (build_dir / name).exists()

    if has("uv.lock"):
        return "uv"
    if has("pdm.lock"):
        return "pdm"
    if has("poetry.lock") or _pyproject_has_section(build_dir, "[tool.poetry]"):
        return "poetry"
    if has("Pipfile.lock") or has("Pipfile"):
        return "pipenv"
    if has("pyproject.toml"):
        return "uv"
    if has("requirements.txt"):
        return "uv-pip"

    raise DependencyManagerError(
        "No recognised Python project (expected a uv/pdm/poetry/pipenv lockfile, "
        "a pyproject.toml, or a requirements.txt)"
    )


def _pyproject_has_section(build_dir: Path, marker: str) -> bool:
    path = build_dir / "pyproject.toml"
    if not path.exists():
        return False
    return marker in path.read_text()
