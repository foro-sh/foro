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

import re
import time
from dataclasses import dataclass

from foro import _api
from foro._api import ApiError

# Every foro token starts with this; the random part follows it.
TOKEN_PREFIX = "foro_pat_"
# The format is fixed server-side: the prefix plus the base64url of 32 CSPRNG
# bytes, unpadded. Worth checking a pasted token against before sending it
# anywhere, so a truncated paste reads as a bad paste rather than as a 401.
TOKEN_RE = re.compile(rf"^{TOKEN_PREFIX}[A-Za-z0-9_-]{{43}}$")

# Fallback widening step, used only when a `slow_down` body arrives without an
# `interval` of its own. The server normally sends the cadence it is enforcing.
SLOW_DOWN_STEP = 5.0
# RFC 8628 §3.2's default, used when the grant's own interval is unusable.
DEFAULT_INTERVAL = 5.0


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
    # A server that sends 0 or a negative cadence would otherwise turn this
    # into a busy loop against its own token endpoint. RFC 8628's default is
    # the floor when the number it sent is not one we can poll on.
    interval = float(grant.interval) if grant.interval > 0 else DEFAULT_INTERVAL
    started = time.monotonic()
    deadline = started + grant.expires_in

    while True:
        # Ask first, sleep after. Sleeping first meant an approval that had
        # already happened - the common case, since the human is sent to the
        # browser before this loop starts - still waited out a full interval
        # before anyone asked the server about it.
        try:
            return _api.request(
                "POST",
                "/api/cli/device/token",
                host=host,
                body={"device_code": grant.device_code},
            )
        except ApiError as err:
            code = err.code
            if code == "slow_down":
                # The server widens its own stored interval and returns it, so
                # poll on that rather than on a locally-guessed number - a
                # guess that lands under what the server now enforces just
                # trips `slow_down` again.
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
    """The interval to adopt after a `slow_down`. Anything the server didn't
    send as a usable positive number falls back to widening locally - taking a
    0 at face value would busy-loop on the endpoint that just asked us to slow
    down, which is the opposite of what it asked for."""
    sent = payload.get("interval") if isinstance(payload, dict) else None
    if isinstance(sent, bool) or not isinstance(sent, (int, float)) or sent <= 0:
        return current + SLOW_DOWN_STEP
    return float(sent)


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
