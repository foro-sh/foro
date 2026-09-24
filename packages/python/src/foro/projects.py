"""List, show, and resolve the directory-to-project link."""

from __future__ import annotations

from pathlib import Path

from foro import _api, _project_link
from foro._project_link import ProjectLink


class ProjectError(Exception):
    pass


def list_projects(host: str, token: str) -> list[dict]:
    return _api.request("GET", "/api/projects", host=host, token=token)


def get_project(host: str, token: str, slug: str) -> dict:
    return _api.request("GET", f"/api/projects/{slug}", host=host, token=token)


def list_deployments(host: str, token: str, slug: str) -> list[dict]:
    return _api.request("GET", f"/api/projects/{slug}/deployments", host=host, token=token)


def resolve_slug(repo_dir: Path, host: str, override: str | None) -> str:
    if override:
        return override
    link = _project_link.load(repo_dir, host)
    if link is None:
        raise ProjectError(
            "this directory isn't linked to a foro.sh project - "
            "run `foro deploy` to create one, or `foro link <slug>` to adopt an existing one"
        )
    return link.slug


def link(repo_dir: Path, host: str, token: str, slug: str) -> dict:
    project = get_project(host, token, slug)
    _project_link.save(repo_dir, ProjectLink(host=host, slug=slug))
    return project
