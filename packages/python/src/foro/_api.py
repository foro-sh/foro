"""HTTP client on stdlib urllib.request."""

from __future__ import annotations

import json
import secrets
import urllib.error
import urllib.request
from collections.abc import Iterator
from importlib.metadata import version
from typing import Any

TIMEOUT = 30.0
UPLOAD_TIMEOUT = 300.0


class ApiError(Exception):
    def __init__(self, status: int, payload: Any, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.payload = payload

    @property
    def code(self) -> str | None:
        if isinstance(self.payload, dict):
            value = self.payload.get("error")
            return value if isinstance(value, str) else None
        return None


def base_url(host: str) -> str:
    # localhost and *.localhost are loopback (RFC 6761). Everything else is TLS.
    name = host.split(":")[0]
    local = name in ("localhost", "127.0.0.1") or name.endswith(".localhost")
    return f"{'http' if local else 'https'}://{host}"


def request(
    method: str,
    path: str,
    *,
    host: str,
    token: str | None = None,
    body: dict | None = None,
    timeout: float = TIMEOUT,
) -> Any:
    req = urllib.request.Request(f"{base_url(host)}{path}", method=method)
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", f"foro-cli/{version('foro')}")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if body is not None:
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(body).encode()

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return _decode(response.read())
    except urllib.error.HTTPError as err:
        payload = _decode(err.read())
        raise ApiError(err.code, payload, _message(payload, err.code, path)) from None
    except urllib.error.URLError as err:
        raise ApiError(0, None, f"could not reach {base_url(host)}: {err.reason}") from None


def post_multipart(
    path: str,
    method: str = "POST",
    *,
    host: str,
    token: str,
    filename: str,
    content: bytes,
    field: str = "file",
) -> Any:
    boundary = f"----foro{secrets.token_hex(16)}"
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'.encode(),
            b"Content-Type: application/zip\r\n\r\n",
            content,
            f"\r\n--{boundary}--\r\n".encode(),
        ]
    )

    req = urllib.request.Request(f"{base_url(host)}{path}", method=method, data=body)
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", f"foro-cli/{version('foro')}")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")

    try:
        with urllib.request.urlopen(req, timeout=UPLOAD_TIMEOUT) as response:
            return _decode(response.read())
    except urllib.error.HTTPError as err:
        payload = _decode(err.read())
        raise ApiError(err.code, payload, _message(payload, err.code, path)) from None
    except urllib.error.URLError as err:
        raise ApiError(0, None, f"could not reach {base_url(host)}: {err.reason}") from None


def stream_sse(path: str, *, host: str, token: str) -> Iterator[dict]:
    """Yield each SSE `data:` payload. `{"done": true}` ends the iterator.
    No read timeout: idle time between heartbeats is expected."""
    req = urllib.request.Request(f"{base_url(host)}{path}")
    req.add_header("Accept", "text/event-stream")
    req.add_header("User-Agent", f"foro-cli/{version('foro')}")
    req.add_header("Authorization", f"Bearer {token}")

    try:
        response = urllib.request.urlopen(req)
    except urllib.error.HTTPError as err:
        payload = _decode(err.read())
        raise ApiError(err.code, payload, _message(payload, err.code, path)) from None
    except urllib.error.URLError as err:
        raise ApiError(0, None, f"could not reach {base_url(host)}: {err.reason}") from None

    with response:
        for raw in response:
            line = raw.decode(errors="replace").rstrip("\r\n")
            if not line.startswith("data:"):
                continue
            try:
                payload = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and payload.get("done"):
                return
            yield payload


def explain(err: ApiError, *, action: str) -> str:
    reason = err.payload.get("reason") if isinstance(err.payload, dict) else None
    message = err.payload.get("error") if isinstance(err.payload, dict) else None

    if err.status == 401:
        return "not logged in, or your token was revoked - run `foro auth login`"
    if err.status == 403:
        if message == "workspace_required" or reason == "workspace_required":
            return "finish onboarding in the dashboard first - your account has no workspace yet"
        if reason == "seat_read_only":
            return "your seat is read-only on this workspace's plan"
        if reason == "repo_provider_not_connected":
            return "connect a repo provider in the dashboard before deploying from a repo"
        return message or f"not allowed to {action}"
    if err.status == 429:
        if reason == "global_capacity":
            return "the platform is at capacity right now - not your quota; try again shortly"
        return message or "your plan's server limit is used up - upgrade or remove a server"
    if err.status == 503:
        return message or "object storage isn't configured on this instance, so uploads are off"
    if err.status == 409:
        return message or f"cannot {action} right now"
    return message or str(err)


def _message(payload: Any, status: int, path: str) -> str:
    if isinstance(payload, dict) and isinstance(payload.get("error"), str):
        return payload["error"]
    return f"HTTP {status} from {path}"


def _decode(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw.decode(errors="replace")
