"""Device-code login (RFC 8628) against foro.sh's CLI endpoints."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from foro import _api
from foro._api import ApiError

TOKEN_PREFIX = "foro_pat_"
# Prefix plus unpadded base64url of 32 CSPRNG bytes.
TOKEN_RE = re.compile(rf"^{TOKEN_PREFIX}[A-Za-z0-9_-]{{43}}$")

SLOW_DOWN_STEP = 5.0
DEFAULT_INTERVAL = 5.0  # RFC 8628 §3.2


class AuthError(Exception):
    pass


@dataclass
class DeviceGrant:
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int
    interval: int


@dataclass
class Identity:
    user: str
    workspace: str | None


def _object(payload, what: str) -> dict:
    if not isinstance(payload, dict):
        raise AuthError(f"{what} was not a JSON object - is this a foro.sh instance?")
    return payload


def _string(payload: dict, key: str, what: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise AuthError(f"{what} is missing `{key}`")
    return value


def _is_positive_number(value) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and value > 0


def _positive_int(payload: dict, key: str, what: str) -> int:
    value = payload.get(key)
    if not _is_positive_number(value):
        raise AuthError(f"{what} is missing a usable `{key}`")
    return int(value)


def _optional_positive_int(payload: dict, key: str, default: int) -> int:
    value = payload.get(key)
    return int(value) if _is_positive_number(value) else default


def start_device_flow(host: str, label: str) -> DeviceGrant:
    payload = _object(
        _api.request("POST", "/api/cli/device/code", host=host, body={"label": label}),
        "the device-code response",
    )
    what = "the device-code response"
    return DeviceGrant(
        device_code=_string(payload, "device_code", what),
        user_code=_string(payload, "user_code", what),
        verification_uri=_string(payload, "verification_uri", what),
        verification_uri_complete=_string(payload, "verification_uri_complete", what),
        expires_in=_positive_int(payload, "expires_in", what),
        interval=_optional_positive_int(payload, "interval", int(DEFAULT_INTERVAL)),
    )


def poll_for_token(host: str, grant: DeviceGrant, on_wait=None) -> dict:
    interval = float(grant.interval) if grant.interval > 0 else DEFAULT_INTERVAL
    started = time.monotonic()
    deadline = started + grant.expires_in

    while True:
        try:
            payload = _object(
                _api.request(
                    "POST",
                    "/api/cli/device/token",
                    host=host,
                    body={"device_code": grant.device_code},
                ),
                "the device-token response",
            )
            _string(payload, "access_token", "the device-token response")
            return payload
        except ApiError as err:
            code = err.code
            if code == "slow_down":
                interval = _widened(err.payload, interval)
            elif code == "expired_token":
                raise AuthError(
                    "the code expired before it was authorized - run `foro auth login` again"
                ) from None
            elif code == "access_denied":
                raise AuthError("authorization was denied in the browser") from None
            elif code != "authorization_pending":
                raise

        if time.monotonic() >= deadline:
            raise AuthError("the code expired before it was authorized - run `foro auth login` again")

        if on_wait:
            on_wait(time.monotonic() - started)
        time.sleep(interval)


def _widened(payload, current: float) -> float:
    sent = payload.get("interval") if isinstance(payload, dict) else None
    return float(sent) if _is_positive_number(sent) else current + SLOW_DOWN_STEP


def fetch_identity(host: str, token: str) -> Identity:
    payload = _object(_api.request("GET", "/api/users/me", host=host, token=token), "/users/me")
    user = payload.get("repo_username") or payload.get("email") or payload.get("id")
    if not isinstance(user, str) or not user:
        raise AuthError("/users/me identified no user - is this a foro.sh instance?")
    workspace = payload.get("workspace")
    name = workspace.get("name") if isinstance(workspace, dict) else None
    return Identity(user=user, workspace=name if isinstance(name, str) else None)


def revoke(host: str, token: str) -> None:
    if not token.startswith(TOKEN_PREFIX):
        raise AuthError(f"this does not look like a foro token (no {TOKEN_PREFIX} prefix)")
    prefix = token[len(TOKEN_PREFIX) :][:8]

    rows = _api.request("GET", "/api/cli/tokens", host=host, token=token)
    if not isinstance(rows, list):
        raise AuthError("the token list was not a JSON array - is this a foro.sh instance?")
    matches = [
        row for row in rows if isinstance(row, dict) and row.get("token_prefix") == prefix
    ]

    if not matches:
        raise AuthError("the server does not list this token - it is already revoked")
    if len(matches) > 1:
        raise AuthError(
            "more than one token matches this prefix - revoke it on /account instead"
        )

    raw_id = matches[0].get("id")
    token_id = str(raw_id) if isinstance(raw_id, (str, int)) and not isinstance(raw_id, bool) else ""
    if not token_id or "/" in token_id or token_id in (".", ".."):
        raise AuthError("the matched token row has no usable `id` - revoke it on /account instead")

    _api.request("DELETE", f"/api/cli/tokens/{token_id}", host=host, token=token)
