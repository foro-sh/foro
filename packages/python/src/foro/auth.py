"""`foro auth` - the device-code flow that gets a CLI token onto this machine.

RFC 8628-shaped on the wire, against foro.sh's own endpoints rather than an
OIDC provider's (see foro-sh/platform#551 for why): the CLI asks for a code,
the human approves it in a browser, and the CLI polls until the grant is
resolved. The polling loop is the part that's easy to get subtly wrong, so it
implements the documented state machine rather than "retry until something
works" - in particular `slow_down` means *poll on the interval the server sends
back with it*, not retry at the old rate.

The token is workspace-scoped, chosen at approval time, so there is no
workspace-switch verb here: a user who wants CLI access to two workspaces logs
in twice and gets two tokens.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from foro import _api
from foro._api import ApiError

# Every foro token starts with this; the random part follows it.
TOKEN_PREFIX = "foro_pat_"

# Fallback widening step, used only when a `slow_down` body arrives without an
# `interval` of its own. The server normally sends the cadence it is enforcing.
SLOW_DOWN_STEP = 5.0


class AuthError(Exception):
    """The flow ended without a token, for a reason worth showing verbatim."""


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


def start_device_flow(host: str, label: str) -> DeviceGrant:
    payload = _api.request(
        "POST", "/api/cli/device/code", host=host, body={"label": label}
    )
    return DeviceGrant(
        device_code=payload["device_code"],
        user_code=payload["user_code"],
        verification_uri=payload["verification_uri"],
        verification_uri_complete=payload["verification_uri_complete"],
        expires_in=int(payload["expires_in"]),
        interval=int(payload["interval"]),
    )


def poll_for_token(host: str, grant: DeviceGrant, on_wait=None) -> dict:
    """Block until the grant is approved, denied, or expires.

    `on_wait(elapsed)` is called before each sleep so the caller can render
    progress - this loop owns the timing, not the display.
    """
    interval = float(grant.interval)
    started = time.monotonic()
    deadline = started + grant.expires_in

    while True:
        if on_wait:
            on_wait(time.monotonic() - started)
        time.sleep(interval)

        if time.monotonic() >= deadline:
            raise AuthError("the code expired before it was authorized - run `foro auth login` again")

        try:
            return _api.request(
                "POST",
                "/api/cli/device/token",
                host=host,
                body={"device_code": grant.device_code},
            )
        except ApiError as err:
            code = err.code
            if code == "authorization_pending":
                continue
            if code == "slow_down":
                # The server widens its own stored interval and returns it, so
                # poll on that rather than on a locally-guessed number - a
                # guess that lands under what the server now enforces just
                # trips `slow_down` again.
                sent = err.payload.get("interval") if isinstance(err.payload, dict) else None
                interval = float(sent) if sent else interval + SLOW_DOWN_STEP
                continue
            if code == "expired_token":
                raise AuthError(
                    "the code expired before it was authorized - run `foro auth login` again"
                ) from None
            if code == "access_denied":
                raise AuthError("authorization was denied in the browser") from None
            raise


def fetch_identity(host: str, token: str) -> Identity:
    """Prove a token works, and find out who it belongs to. This is what makes
    `status` report a revoked token as broken rather than as logged in."""
    payload = _api.request("GET", "/api/users/me", host=host, token=token)
    # /users/me has no display name - repo_username is what the dashboard
    # shows, with email as the fallback for a Zitadel sign-in that hasn't
    # connected a repo provider yet.
    user = payload.get("repo_username") or payload.get("email") or payload["id"]
    workspace = payload.get("workspace")
    return Identity(user=user, workspace=workspace["name"] if workspace else None)


def revoke(host: str, token: str) -> None:
    """Revoke a token server-side, finding its id by prefix first.

    The CLI never learns its own token's id - the poll response deliberately
    doesn't carry one (platform#574), and a `--with-token` login never saw a
    poll at all. So logout lists the caller's tokens and matches on
    `token_prefix`, the first 8 characters of the random part.
    """
    prefix = token[len(TOKEN_PREFIX) :][:8]
    rows = _api.request("GET", "/api/cli/tokens", host=host, token=token)
    matches = [row for row in rows if row.get("token_prefix") == prefix]

    if not matches:
        raise AuthError("the server does not list this token - it is already revoked")
    if len(matches) > 1:
        # token_prefix is nominally a display field. A collision across one
        # user's handful of tokens is unreachable at 48 bits, but deleting
        # somebody's wrong credential is worse than deleting none.
        raise AuthError(
            "more than one token matches this prefix - revoke it on /account instead"
        )

    _api.request("DELETE", f"/api/cli/tokens/{matches[0]['id']}", host=host, token=token)
