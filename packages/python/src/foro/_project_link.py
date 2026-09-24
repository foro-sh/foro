"""Directory-to-project link. Stored in `.foro/` so a committed slug cannot
point a fork at someone else's project."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

LINK_DIR = ".foro"
LINK_FILE = "project.json"
GITIGNORE_ENTRY = ".foro/"


@dataclass
class ProjectLink:
    host: str
    slug: str
    workspace: str | None = None


def link_path(repo_dir: Path) -> Path:
    return repo_dir / LINK_DIR / LINK_FILE


def load(repo_dir: Path, host: str) -> ProjectLink | None:
    path = link_path(repo_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict) or data.get("host") != host:
            return None
        return ProjectLink(host=data["host"], slug=data["slug"], workspace=data.get("workspace"))
    except (OSError, ValueError, KeyError):
        return None


def save(repo_dir: Path, link: ProjectLink) -> None:
    path = link_path(repo_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"host": link.host, "slug": link.slug, "workspace": link.workspace}, indent=2)
        + "\n"
    )


def delete(repo_dir: Path) -> bool:
    path = link_path(repo_dir)
    if not path.exists():
        return False
    path.unlink()
    return True


def is_gitignored(repo_dir: Path) -> bool:
    gitignore = repo_dir / ".gitignore"
    if not gitignore.exists():
        return False
    return any(line.strip().rstrip("/") == LINK_DIR for line in gitignore.read_text().splitlines())


def add_to_gitignore(repo_dir: Path) -> None:
    gitignore = repo_dir / ".gitignore"
    existing = gitignore.read_text() if gitignore.exists() else ""
    prefix = "" if existing.endswith("\n") or not existing else "\n"
    gitignore.write_text(f"{existing}{prefix}{GITIGNORE_ENTRY}\n")
