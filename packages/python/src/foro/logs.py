"""Runtime logs (container stdout) and per-deployment deploy/build logs."""

from __future__ import annotations

from foro import _api


def stream_runtime(host: str, token: str, slug: str):
    return _api.stream_sse(f"/api/projects/{slug}/logs/stream", host=host, token=token)


def read_runtime(host: str, token: str, slug: str) -> list[dict]:
    payload = _api.request("GET", f"/api/projects/{slug}/logs", host=host, token=token)
    return payload.get("lines", []) if isinstance(payload, dict) else []


def read_deployment(host: str, token: str, slug: str, deployment_id: str, kind: str) -> list[dict]:
    payload = _api.request(
        "GET",
        f"/api/projects/{slug}/deployments/{deployment_id}/{kind}",
        host=host,
        token=token,
    )
    return payload.get("lines", []) if isinstance(payload, dict) else []


def latest_deployment_id(host: str, token: str, slug: str) -> str | None:
    rows = _api.request("GET", f"/api/projects/{slug}/deployments", host=host, token=token)
    return rows[0]["id"] if rows else None
