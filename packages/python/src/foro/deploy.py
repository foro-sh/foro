"""Create or update a project, then trigger a build."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from foro import _api, _archive, _project_link
from foro._project_link import ProjectLink

IN_FLIGHT = ("queued", "building", "starting")


class DeployError(Exception):
    pass


@dataclass
class Started:
    slug: str
    deployment_id: str
    url: str
    created: bool


def local_changes_warning(repo_dir: Path) -> str | None:
    def git(*args: str) -> str | None:
        try:
            done = subprocess.run(
                ["git", *args], cwd=repo_dir, capture_output=True, check=True
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None
        return done.stdout.decode().strip()

    if git("rev-parse", "--git-dir") is None:
        return None

    excluded = []
    if git("status", "--porcelain"):
        excluded.append("uncommitted changes")
    unpushed = git("rev-list", "--count", "@{u}..HEAD")
    no_upstream = unpushed is None
    if not no_upstream and unpushed != "0":
        excluded.append(f"{unpushed} unpushed commit(s)")

    parts = []
    if excluded:
        parts.append(
            "this project builds from its repo branch, so "
            + " and ".join(excluded)
            + " will not be included"
        )
    if no_upstream:
        parts.append("this branch has no upstream, so nothing here has been pushed")
    return "; ".join(parts) or None


def deploy(
    repo_dir: Path,
    host: str,
    token: str,
    *,
    slug: str | None = None,
    force_upload: bool = False,
    force_repo: bool = False,
    on_step=None,
) -> Started:
    def step(message: str) -> None:
        if on_step:
            on_step(message)

    link = _project_link.load(repo_dir, host) if slug is None else ProjectLink(host, slug)
    created = False

    if link is None:
        if force_repo:
            raise DeployError(
                "--repo needs a project that already deploys from a repo; "
                "this directory isn't linked to one"
            )
        step("creating a new project from this directory")
        project = _create_from_upload(repo_dir, host, token, step)
        _project_link.save(repo_dir, ProjectLink(host=host, slug=project["slug"]))
        created = True
    else:
        project = _api.request("GET", f"/api/projects/{link.slug}", host=host, token=token)
        use_upload = force_upload or (project["source"] == "upload" and not force_repo)
        if use_upload:
            if project["source"] != "upload":
                raise DeployError(
                    f"{project['slug']} deploys from a repo, so there is no archive to replace"
                )
            step("uploading the working tree")
            _replace_upload(repo_dir, host, token, project["slug"], step)
        else:
            warning = local_changes_warning(repo_dir)
            if warning:
                step(f"warning: {warning}")

    started = _api.request(
        "POST", f"/api/projects/{project['slug']}/deploy", host=host, token=token
    )
    return Started(
        slug=project["slug"],
        deployment_id=started["id"],
        url=project["url"],
        created=created,
    )


def _create_from_upload(repo_dir: Path, host: str, token: str, step) -> dict:
    archive = _build(repo_dir, step)
    return _api.post_multipart(
        "/api/projects/upload",
        host=host,
        token=token,
        filename="project.zip",
        content=archive.content,
    )


def _replace_upload(repo_dir: Path, host: str, token: str, slug: str, step) -> None:
    archive = _build(repo_dir, step)
    _api.post_multipart(
        f"/api/projects/{slug}/upload",
        method="PUT",
        host=host,
        token=token,
        filename="project.zip",
        content=archive.content,
    )


def _build(repo_dir: Path, step) -> _archive.Archive:
    archive = _archive.build(repo_dir)
    step(f"packaged {archive.file_count} files ({archive.size / 1024 / 1024:.1f} MiB)")
    return archive


def stream_deploy(host: str, token: str, slug: str, deployment_id: str):
    return _api.stream_sse(
        f"/api/projects/{slug}/deployments/{deployment_id}/deploy/stream",
        host=host,
        token=token,
    )


def stream_build(host: str, token: str, slug: str, deployment_id: str):
    return _api.stream_sse(
        f"/api/projects/{slug}/deployments/{deployment_id}/build/stream",
        host=host,
        token=token,
    )


def get_deployment(host: str, token: str, slug: str, deployment_id: str) -> dict:
    return _api.request(
        "GET", f"/api/projects/{slug}/deployments/{deployment_id}", host=host, token=token
    )
