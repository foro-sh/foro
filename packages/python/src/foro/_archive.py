"""Build the zip `foro deploy` uploads.

`pyproject.toml` or `package.json` must sit at the archive root. File
selection uses `git ls-files --cached --others --exclude-standard` when
git is available; otherwise a walk with the same exclusions.
"""

from __future__ import annotations

import subprocess
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from foro._manifest import CONFIG_FILES

MAX_UPLOAD_BYTES = 50 * 1024 * 1024

ALWAYS_EXCLUDED_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", "dist", ".foro"}


class ArchiveError(Exception):
    pass


@dataclass
class Archive:
    content: bytes
    file_count: int

    @property
    def size(self) -> int:
        return len(self.content)


def _is_excluded(rel: Path) -> bool:
    if ALWAYS_EXCLUDED_DIRS & set(rel.parts):
        return True
    name = rel.name
    return name.startswith(".env") and name != ".env.example"


def _git_tracked_files(repo_dir: Path) -> list[Path] | None:
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=repo_dir,
            capture_output=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return [Path(name) for name in result.stdout.decode().split("\0") if name]


def _walked_files(repo_dir: Path) -> list[Path]:
    return [
        path.relative_to(repo_dir)
        for path in repo_dir.rglob("*")
        if path.is_file() and not _is_excluded(path.relative_to(repo_dir))
    ]


def collect_files(repo_dir: Path) -> list[Path]:
    tracked = _git_tracked_files(repo_dir)
    candidates = tracked if tracked is not None else _walked_files(repo_dir)
    return sorted(
        rel for rel in candidates if not _is_excluded(rel) and (repo_dir / rel).is_file()
    )


def build(repo_dir: Path) -> Archive:
    files = collect_files(repo_dir)
    root_names = {rel.as_posix() for rel in files}
    if not any(name in root_names for name in CONFIG_FILES.values()):
        raise ArchiveError(
            "no pyproject.toml or package.json at the root of this directory - "
            "run `foro init` here first"
        )

    buffer = BytesIO()
    # zipfile raises on mtimes before 1980 unless this is off.
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, strict_timestamps=False) as archive:
        for rel in files:
            # as_posix(): a zip built on Windows must extract to Linux paths.
            archive.write(repo_dir / rel, arcname=rel.as_posix())

    content = buffer.getvalue()
    if len(content) > MAX_UPLOAD_BYTES:
        raise ArchiveError(
            f"the archive is {len(content) / 1024 / 1024:.1f} MiB, over the "
            f"{MAX_UPLOAD_BYTES // 1024 // 1024} MiB upload limit - "
            "add what doesn't belong in the build to .gitignore"
        )
    return Archive(content=content, file_count=len(files))
