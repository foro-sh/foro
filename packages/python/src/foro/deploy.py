"""`foro deploy` - working tree to a live URL.

The design fork is what an unlinked directory means. It deploys as an *upload*
project: `check` and `dev` already operate on the working tree, and "`foro dev`
passed, now ship exactly that" is the promise the CLI makes. Requiring a GitHub
remote, a push, and a repo-picker round trip before the first deploy throws
away the one thing a terminal is good at.

A directory already linked to a `github` project is the opposite case: that
project builds from its branch, so uploading the working tree would be a lie.
There the CLI triggers the branch build and warns about anything local that
won't be in it - the single most likely "why isn't my change live" question,
answered before it's asked.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from foro import _api, _archive, _project_link
from foro._project_link import ProjectLink

# What POST /projects/:slug/deploy answers with while the worker builds.
IN_FLIGHT = ("queued", "building", "starting")


class DeployError(Exception):
    """The deploy could not be started, with a reason worth showing."""


@dataclass
class Started:
    slug: str
    deployment_id: str
    url: str
    created: bool


def local_changes_warning(repo_dir: Path) -> str | None:
    """What a branch build will *not* contain. None when the tree is clean and
    pushed, or when this isn't a git repo (nothing to compare against)."""
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
    # Fails when the branch has no upstream, which is its own, worse problem.
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
    """Create or update the project as needed, then trigger the build.

    `on_step(message)` reports progress; this owns the decisions, not the
    printing.
    """
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
    """The orchestration narrative: clone, manifest validation, container
    lifecycle, health check, failure reason."""
    return _api.stream_sse(
        f"/api/projects/{slug}/deployments/{deployment_id}/deploy/stream",
        host=host,
        token=token,
    )


def stream_build(host: str, token: str, slug: str, deployment_id: str):
    """Raw `docker build` stdout/stderr - a separate channel from the deploy
    narrative, and usually where a failure's actual cause is."""
    return _api.stream_sse(
        f"/api/projects/{slug}/deployments/{deployment_id}/build/stream",
        host=host,
        token=token,
    )


def get_deployment(host: str, token: str, slug: str, deployment_id: str) -> dict:
    return _api.request(
        "GET", f"/api/projects/{slug}/deployments/{deployment_id}", host=host, token=token
    )
