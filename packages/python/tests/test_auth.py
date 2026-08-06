"""The device flow can't be exercised end to end until foro-sh/platform#551
ships the server half, so these drive it against a real HTTP server serving
scripted responses - the state machine, not a mock of it."""

from __future__ import annotations

import json
import os
import stat
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from foro import _config, auth
from foro._api import ApiError


class _Handler(BaseHTTPRequestHandler):
    # Each entry is (status, body); the server pops one per request so a test
    # can script "pending, pending, slow_down, approved".
    script: list = []
    seen: list = []

    def _respond(self):
        self.seen.append((self.command, self.path))
        status, body = self.script.pop(0)
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    do_GET = _respond
    do_POST = _respond
    do_DELETE = _respond

    def log_message(self, *args):  # keep pytest output clean
        pass


@pytest.fixture
def server():
    _Handler.script = []
    _Handler.seen = []
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"127.0.0.1:{httpd.server_port}", _Handler
    httpd.shutdown()


@pytest.fixture(autouse=True)
def no_sleeping(monkeypatch):
    """The loop's real timing would make these tests take a minute."""
    slept = []
    monkeypatch.setattr(auth.time, "sleep", slept.append)
    return slept


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    monkeypatch.delenv(_config.ENV_TOKEN, raising=False)
    monkeypatch.delenv(_config.ENV_HOST, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "config"))


def _grant(interval=5, expires_in=900):
    return auth.DeviceGrant(
        device_code="dev-code",
        user_code="7A2F-K9QP",
        verification_uri="https://foro.sh/cli",
        verification_uri_complete="https://foro.sh/cli?code=7A2F-K9QP",
        expires_in=expires_in,
        interval=interval,
    )


def test_poll_waits_through_pending_then_returns_the_token(server, no_sleeping):
    host, handler = server
    handler.script = [
        (400, {"error": "authorization_pending"}),
        (400, {"error": "authorization_pending"}),
        (200, {"access_token": "foro_pat_abc"}),
    ]

    payload = auth.poll_for_token(host, _grant())

    assert payload["access_token"] == "foro_pat_abc"
    assert len(handler.seen) == 3


def test_slow_down_adopts_the_interval_the_server_sends(server, no_sleeping):
    host, handler = server
    handler.script = [
        (400, {"error": "slow_down", "interval": 12}),
        (200, {"access_token": "foro_pat_abc"}),
    ]

    auth.poll_for_token(host, _grant(interval=5))

    # 12, not 5 + SLOW_DOWN_STEP: the server is enforcing its own cadence and
    # says which one, so a local guess is not the number to poll on. One
    # sleep, not two - the first request goes out before any waiting.
    assert no_sleeping == [12.0]


def test_slow_down_without_an_interval_falls_back_to_the_local_step(server, no_sleeping):
    host, handler = server
    handler.script = [
        (400, {"error": "slow_down"}),
        (200, {"access_token": "foro_pat_abc"}),
    ]

    auth.poll_for_token(host, _grant(interval=5))

    assert no_sleeping == [5.0 + auth.SLOW_DOWN_STEP]


def test_an_already_approved_grant_costs_no_wait_at_all(server, no_sleeping):
    """The human is sent to the browser before this loop starts, so by the
    time it runs the approval is often already in. Sleeping before the first
    request made that common case wait out a full interval for a token the
    server was holding the whole time."""
    host, handler = server
    handler.script = [(200, {"access_token": "foro_pat_abc"})]

    payload = auth.poll_for_token(host, _grant(interval=5))

    assert payload["access_token"] == "foro_pat_abc"
    assert no_sleeping == []


def test_a_zero_interval_from_the_server_does_not_become_a_busy_loop(server, no_sleeping):
    """`float(sent) if sent else ...` read 0 as absent for the slow_down case
    and as a cadence for the grant's own - neither is a number to poll on."""
    host, handler = server
    handler.script = [
        (400, {"error": "authorization_pending"}),
        (400, {"error": "slow_down", "interval": 0}),
        (200, {"access_token": "foro_pat_abc"}),
    ]

    auth.poll_for_token(host, _grant(interval=0))

    assert no_sleeping == [auth.DEFAULT_INTERVAL, auth.DEFAULT_INTERVAL + auth.SLOW_DOWN_STEP]
    assert all(slept > 0 for slept in no_sleeping)


def test_denied_is_reported_as_denial_not_as_a_network_error(server):
    host, handler = server
    handler.script = [(400, {"error": "access_denied"})]

    with pytest.raises(auth.AuthError, match="denied"):
        auth.poll_for_token(host, _grant())


def test_expired_token_stops_the_loop(server):
    host, handler = server
    handler.script = [(400, {"error": "expired_token"})]

    with pytest.raises(auth.AuthError, match="expired"):
        auth.poll_for_token(host, _grant())


def test_unrecognised_error_is_not_swallowed(server):
    host, handler = server
    handler.script = [(500, {"error": "boom"})]

    with pytest.raises(ApiError):
        auth.poll_for_token(host, _grant())


def test_identity_falls_back_to_email_without_a_repo_username(server):
    host, handler = server
    handler.script = [
        (
            200,
            {
                "id": "u-1",
                "repo_username": None,
                "email": "dev@example.com",
                "workspace": {"name": "acme"},
            },
        )
    ]

    identity = auth.fetch_identity(host, "foro_pat_abc")

    assert identity.user == "dev@example.com"
    assert identity.workspace == "acme"


def test_revoke_deletes_the_row_matching_the_token_prefix(server):
    host, handler = server
    token = auth.TOKEN_PREFIX + "a1b2c3d4" + "x" * 35
    handler.script = [
        (200, [
            {"id": "someone-elses", "token_prefix": "zzzzzzzz"},
            {"id": "mine", "token_prefix": "a1b2c3d4"},
        ]),
        (204, {}),
    ]

    auth.revoke(host, token)

    assert handler.seen[1] == ("DELETE", "/api/cli/tokens/mine")


def test_revoke_refuses_to_guess_when_two_rows_share_a_prefix(server):
    host, handler = server
    token = auth.TOKEN_PREFIX + "a1b2c3d4" + "x" * 35
    handler.script = [
        (200, [
            {"id": "one", "token_prefix": "a1b2c3d4"},
            {"id": "two", "token_prefix": "a1b2c3d4"},
        ]),
    ]

    with pytest.raises(auth.AuthError, match="more than one"):
        auth.revoke(host, token)

    # Nothing was deleted - the list call is the only request made.
    assert len(handler.seen) == 1


def test_revoke_says_so_when_the_token_is_already_gone(server):
    host, handler = server
    handler.script = [(200, [])]

    with pytest.raises(auth.AuthError, match="already revoked"):
        auth.revoke(host, auth.TOKEN_PREFIX + "a" * 43)


def test_token_shape_is_checked_before_a_pasted_token_is_used():
    assert auth.TOKEN_RE.match(auth.TOKEN_PREFIX + "a" * 43)
    # A truncated paste, the wrong credential entirely, and a bare secret.
    assert not auth.TOKEN_RE.match(auth.TOKEN_PREFIX + "a" * 42)
    assert not auth.TOKEN_RE.match("ghp_" + "a" * 43)
    assert not auth.TOKEN_RE.match("a" * 43)


def test_only_loopback_hosts_are_addressed_over_plain_http():
    from foro._api import base_url

    # The two dev stacks: native on a port, and Traefik's Host() rule.
    assert base_url("localhost:3001") == "http://localhost:3001"
    assert base_url("127.0.0.1:3001") == "http://127.0.0.1:3001"
    assert base_url("foro.localhost") == "http://foro.localhost"
    # Everything else carries a bearer token and must be TLS - including a
    # lookalike that merely contains the string.
    assert base_url("foro.sh") == "https://foro.sh"
    assert base_url("localhost.evil.example") == "https://localhost.evil.example"


def test_config_round_trip_and_permissions():
    creds = _config.Credentials(token="foro_pat_abc", user="dev", workspace="acme")
    _config.save("foro.sh", creds)

    loaded = _config.load("foro.sh")
    assert loaded.token == "foro_pat_abc"
    assert loaded.workspace == "acme"
    assert not loaded.from_env
    assert stat.S_IMODE(_config.config_path().stat().st_mode) == 0o600
    assert not _config.has_insecure_permissions()

    _config.delete("foro.sh")
    assert _config.load("foro.sh") is None
    # Logging out of the last host leaves nothing behind, not an empty `{}`.
    assert not _config.config_path().exists()


def test_a_world_readable_token_file_is_flagged():
    _config.save("foro.sh", _config.Credentials(token="foro_pat_abc"))
    _config.config_path().chmod(0o644)

    assert _config.has_insecure_permissions()


def test_hosts_are_kept_separate():
    _config.save("foro.sh", _config.Credentials(token="prod"))
    _config.save("localhost:3001", _config.Credentials(token="dev"))

    assert _config.load("foro.sh").token == "prod"
    assert _config.load("localhost:3001").token == "dev"

    _config.delete("localhost:3001")
    assert _config.load("foro.sh").token == "prod"


def test_env_token_overrides_the_file_and_is_never_written_to_it(monkeypatch):
    _config.save("foro.sh", _config.Credentials(token="from-file", user="dev"))
    monkeypatch.setenv(_config.ENV_TOKEN, "from-env")

    loaded = _config.load("foro.sh")
    assert loaded.token == "from-env"
    assert loaded.from_env

    monkeypatch.delenv(_config.ENV_TOKEN)
    assert _config.load("foro.sh").token == "from-file"


def test_foro_host_selects_the_instance(monkeypatch):
    assert _config.resolve_host() == "foro.sh"
    monkeypatch.setenv(_config.ENV_HOST, "localhost:3001")
    assert _config.resolve_host() == "localhost:3001"


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits only")
def test_saving_never_leaves_the_file_group_or_world_readable():
    _config.save("foro.sh", _config.Credentials(token="foro_pat_abc"))
    mode = _config.config_path().stat().st_mode
    assert not mode & (stat.S_IRWXG | stat.S_IRWXO)


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits only")
def test_saving_narrows_a_file_that_was_already_too_open():
    """The case the test above cannot see: os.open's mode argument applies
    only when it creates the file, so a hosts.yml that already existed as
    0644 - restored dotfiles, a bad umask under an older version, a file a
    user made by hand - kept that mode and took the token anyway."""
    path = _config.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n")
    path.chmod(0o644)

    _config.save("foro.sh", _config.Credentials(token="foro_pat_abc"))

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not _config.has_insecure_permissions()
