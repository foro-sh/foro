"""`foro logs` - the two log sources, which are different things.

Runtime logs are the deployed container's stdout/stderr, live over SSE or read
back from object storage with plan-gated retention (Free 24h → Enterprise 90d),
so an empty history on Free is normal rather than broken. Deploy and build logs
belong to one deployment and are what `foro deploy` streams live; reading them
back after the fact is how "what went wrong in that build" gets answered.
"""

from __future__ import annotations

from foro import _api


def stream_runtime(host: str, token: str, slug: str):
    return _api.stream_sse(f"/api/projects/{slug}/logs/stream", host=host, token=token)


def read_runtime(host: str, token: str, slug: str) -> list[dict]:
    payload = _api.request("GET", f"/api/projects/{slug}/logs", host=host, token=token)
    return payload.get("lines", [])


def read_deployment(host: str, token: str, slug: str, deployment_id: str, kind: str) -> list[dict]:
    """`kind` is 'deploy' (the orchestration narrative) or 'build' (raw docker
    output) - the platform persists them as separate objects."""
    payload = _api.request(
        "GET",
        f"/api/projects/{slug}/deployments/{deployment_id}/{kind}",
        host=host,
        token=token,
    )
    return payload.get("lines", [])


def latest_deployment_id(host: str, token: str, slug: str) -> str | None:
    rows = _api.request("GET", f"/api/projects/{slug}/deployments", host=host, token=token)
    return rows[0]["id"] if rows else None
