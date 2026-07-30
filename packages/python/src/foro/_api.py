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
import urllib.error
import urllib.request
from importlib.metadata import version
from typing import Any

TIMEOUT = 30.0


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
        message = payload.get("error") if isinstance(payload, dict) else None
        raise ApiError(err.code, payload, message or f"HTTP {err.code} from {path}") from None
    except urllib.error.URLError as err:
        raise ApiError(0, None, f"could not reach {base_url(host)}: {err.reason}") from None


def _decode(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # A proxy or error page rather than the API - keep the text, the
        # caller's message is more useful with it than without.
        return raw.decode(errors="replace")
