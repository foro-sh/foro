"""Runtime logs (container stdout) and per-deployment deploy/build logs."""

from __future__ import annotations

from urllib.parse import urlencode

from foro import _api


def stream_runtime(host: str, token: str, slug: str, *, workspace: str | None = None):
    return _api.stream_sse(f"/api/projects/{slug}/logs/stream", host=host, token=token, workspace=workspace)


def read_runtime(
    host: str, token: str, slug: str, *, workspace: str | None = None, **query: str
) -> dict:
    """`query` is passed through: `from`, `to` (ISO-8601) and `q`."""
    suffix = f"?{urlencode(query)}" if query else ""
    payload = _api.request(
        "GET", f"/api/projects/{slug}/logs{suffix}", host=host, token=token, workspace=workspace
    )
    return payload if isinstance(payload, dict) else {}


def summarize(host: str, token: str, slug: str, since: str, *, workspace: str | None = None) -> dict:
    return _api.request(
        "GET",
        f"/api/projects/{slug}/logs/summary?{urlencode({'from': since})}",
        host=host,
        token=token,
        workspace=workspace,
    )


def read_deployment(
    host: str, token: str, slug: str, deployment_id: str, kind: str, *, workspace: str | None = None
) -> list[dict]:
    payload = _api.request(
        "GET",
        f"/api/projects/{slug}/deployments/{deployment_id}/{kind}",
        host=host,
        token=token,
        workspace=workspace,
    )
    return payload.get("lines", []) if isinstance(payload, dict) else []


def latest_deployment_id(host: str, token: str, slug: str, *, workspace: str | None = None) -> str | None:
    rows = _api.request(
        "GET", f"/api/projects/{slug}/deployments", host=host, token=token, workspace=workspace
    )
    return rows[0]["id"] if rows else None
