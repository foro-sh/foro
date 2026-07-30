"""Build the zip `foro deploy` uploads.

The platform's contract (apps/api/src/services/upload.ts) is strict in two
ways worth encoding here rather than discovering as a 422: `foro.yaml` must sit
at the *archive root* (zip the contents, not the folder containing them), and
the compressed archive must fit in 50 MiB.

File selection defers to git rather than parsing .gitignore: in a repo,
`git ls-files --cached --others --exclude-standard` is exactly the set git
would track, which already honours .gitignore, ~/.config/git/ignore and
.git/info/exclude - none of which a hand-rolled matcher would get right.
Outside a repo it falls back to a walk with the same exclusions git's default
ignore would have caught anyway.
"""

from __future__ import annotations

import subprocess
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

# Mirrors MAX_UPLOAD_BYTES in apps/api/src/services/upload.ts, which 413s past
# it - checked here so the failure names the offending files instead.
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

# Applied whatever git says. A tracked .env would otherwise ship secrets into
# the build context, which is the exact thing `foro secrets` exists to avoid,
# and a committed .venv is just a slow 413.
ALWAYS_EXCLUDED_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", "dist", ".foro"}


class ArchiveError(Exception):
    """The working tree can't be packaged, with a reason worth showing."""


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
    # .env.example is documentation and safe; .env, .env.local and friends are
    # not. `foro init` scaffolds the former, so don't strip it.
    name = rel.name
    return name.startswith(".env") and name != ".env.example"


def _git_tracked_files(repo_dir: Path) -> list[Path] | None:
    """Everything git would consider part of the tree, ignored files excluded.
    None when this isn't a git repo (or git isn't installed)."""
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
    # A file can be tracked by git and still have no business in a build
    # context, so the exclusions apply to git's answer too.
    return sorted(
        rel for rel in candidates if not _is_excluded(rel) and (repo_dir / rel).is_file()
    )


def build(repo_dir: Path) -> Archive:
    files = collect_files(repo_dir)
    if not any(rel == Path("foro.yaml") for rel in files):
        raise ArchiveError(
            "no foro.yaml at the root of this directory - run `foro init` here first"
        )

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for rel in files:
            # as_posix(), because a zip built on Windows must still extract to
            # the same paths the Linux build container expects.
            archive.write(repo_dir / rel, arcname=rel.as_posix())

    content = buffer.getvalue()
    if len(content) > MAX_UPLOAD_BYTES:
        raise ArchiveError(
            f"the archive is {len(content) / 1024 / 1024:.1f} MiB, over the "
            f"{MAX_UPLOAD_BYTES // 1024 // 1024} MiB upload limit - "
            "add what doesn't belong in the build to .gitignore"
        )
    return Archive(content=content, file_count=len(files))
