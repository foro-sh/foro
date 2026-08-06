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


# Every response below is read as a shape, not trusted as one. A 2xx is not a
# promise about the body: a captive portal, a proxy error page, or a
# misrouted request all answer 200 with something else entirely, and _api's
# decoder hands back a plain string when the body wasn't JSON. Indexing that
# raises TypeError or KeyError from inside the auth module, which reaches the
# user as a traceback naming a dict key - so each of these says what was
# wrong with the response instead.
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
        # RFC 8628 §3.2 makes `interval` optional and defaults it to 5, so a
        # server that omits it is answering correctly, not badly.
        interval=_optional_positive_int(payload, "interval", int(DEFAULT_INTERVAL)),
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
            payload = _object(
                _api.request(
                    "POST",
                    "/api/cli/device/token",
                    host=host,
                    body={"device_code": grant.device_code},
                ),
                "the device-token response",
            )
            # Checked here rather than at the call site: a 200 with no usable
            # token is this loop's failure to report, and `payload["access_token"]`
            # in cli.py was a bare KeyError traceback.
            _string(payload, "access_token", "the device-token response")
            return payload
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
    return float(sent) if _is_positive_number(sent) else current + SLOW_DOWN_STEP


def fetch_identity(host: str, token: str) -> Identity:
    """Prove a token works, and find out who it belongs to. This is what makes
    `status` report a revoked token as broken rather than as logged in."""
    payload = _object(_api.request("GET", "/api/users/me", host=host, token=token), "/users/me")
    # /users/me has no display name - repo_username is what the dashboard
    # shows, with email as the fallback for a Zitadel sign-in that hasn't
    # connected a repo provider yet.
    user = payload.get("repo_username") or payload.get("email") or payload.get("id")
    if not isinstance(user, str) or not user:
        raise AuthError("/users/me identified no user - is this a foro.sh instance?")
    workspace = payload.get("workspace")
    name = workspace.get("name") if isinstance(workspace, dict) else None
    return Identity(user=user, workspace=name if isinstance(name, str) else None)


def revoke(host: str, token: str) -> None:
    """Revoke a token server-side, finding its id by prefix first.

    The CLI never learns its own token's id - the poll response deliberately
    doesn't carry one (platform#574), and a `--with-token` login never saw a
    poll at all. So logout lists the caller's tokens and matches on
    `token_prefix`, the first 8 characters of the random part.
    """
    if not token.startswith(TOKEN_PREFIX):
        # Nothing downstream would notice: slicing a token of another shape
        # just yields the wrong eight characters, and the request that follows
        # then matches nothing, or - far worse - something else.
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
        # token_prefix is nominally a display field. A collision across one
        # user's handful of tokens is unreachable at 48 bits, but deleting
        # somebody's wrong credential is worse than deleting none.
        raise AuthError(
            "more than one token matches this prefix - revoke it on /account instead"
        )

    # The id goes straight into the DELETE path, so it has to be one path
    # segment and nothing else - a value carrying `/` or `..` would aim the
    # delete at a different endpoint than the one meant.
    raw_id = matches[0].get("id")
    token_id = str(raw_id) if isinstance(raw_id, (str, int)) and not isinstance(raw_id, bool) else ""
    if not token_id or "/" in token_id or token_id in (".", ".."):
        raise AuthError("the matched token row has no usable `id` - revoke it on /account instead")

    _api.request("DELETE", f"/api/cli/tokens/{token_id}", host=host, token=token)
