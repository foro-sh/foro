"""The CLI's HTTP layer, on stdlib `urllib.request`.

Deliberately no dependency: a login command is not worth adding httpx for.
The cost is verbosity - POSTing JSON by hand, and reading error bodies off
non-2xx responses, which matters more than it sounds like because the device
flow's whole state machine lives in 400 bodies. `HTTPError` *is* the response,
so `ApiError.payload` carries the parsed body rather than losing it.

Everything goes through here so that if a later command makes the stdlib route
genuinely painful, swapping the implementation is this one file and no call
sites.
"""

from __future__ import annotations

import json
import secrets
import urllib.error
import urllib.request
from collections.abc import Iterator
from importlib.metadata import version
from typing import Any

TIMEOUT = 30.0
# A 50 MiB archive on a domestic uplink takes longer than a JSON round trip.
UPLOAD_TIMEOUT = 300.0


class ApiError(Exception):
    """A non-2xx response. `payload` is the decoded body when it was JSON."""

    def __init__(self, status: int, payload: Any, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.payload = payload

    @property
    def code(self) -> str | None:
        """The `error` field the device-grant endpoints answer with."""
        if isinstance(self.payload, dict):
            value = self.payload.get("error")
            return value if isinstance(value, str) else None
        return None


def base_url(host: str) -> str:
    # A native dev stack serves plain HTTP on localhost; nothing else does.
    scheme = "http" if host.split(":")[0] in ("localhost", "127.0.0.1") else "https"
    return f"{scheme}://{host}"


def request(
    method: str,
    path: str,
    *,
    host: str,
    token: str | None = None,
    body: dict | None = None,
    timeout: float = TIMEOUT,
) -> Any:
    """Returns the decoded JSON body, or None for an empty 2xx (204s)."""
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
    """The upload routes are @fastify/multipart, and urllib has no encoder -
    so this builds the body by hand. ~20 lines is the price of not adding a
    dependency for two endpoints."""
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
    """Yield each SSE payload until the `{"done": true}` sentinel closes the
    stream.

    Three things the server's shape dictates: `:ping` comment lines are
    heartbeats and carry no data; the sentinel is how a finished deploy is
    signalled, so it terminates the iterator rather than being yielded; and no
    read timeout is set, because an idle-but-healthy stream between heartbeats
    is normal and killing it would look like a failed deploy.
    """
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
    """Turn an API refusal into a sentence that says what to do about it.

    Every one of these is a real reply from the platform - a raw JSON dump
    would leave the user to work out which of them they hit.
    """
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
    # 422's message is already written for a human, and 404/500 carry the
    # server's own wording - print it rather than inventing a worse one.
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
        # A proxy or error page rather than the API - keep the text, the
        # caller's message is more useful with it than without.
        return raw.decode(errors="replace")
