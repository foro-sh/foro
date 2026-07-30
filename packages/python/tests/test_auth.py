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
        (200, {"access_token": "foro_pat_abc", "token_id": "tok-1"}),
    ]

    payload = auth.poll_for_token(host, _grant())

    assert payload["access_token"] == "foro_pat_abc"
    assert len(handler.seen) == 3


def test_slow_down_increases_the_interval(server, no_sleeping):
    host, handler = server
    handler.script = [
        (400, {"error": "slow_down"}),
        (200, {"access_token": "foro_pat_abc"}),
    ]

    auth.poll_for_token(host, _grant(interval=5))

    # The signal exists to be obeyed: the second wait is longer than the first.
    assert no_sleeping == [5.0, 5.0 + auth.SLOW_DOWN_STEP]


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


def test_config_round_trip_and_permissions():
    creds = _config.Credentials(token="foro_pat_abc", user="dev", workspace="acme", token_id="tok-1")
    _config.save("foro.sh", creds)

    loaded = _config.load("foro.sh")
    assert loaded.token == "foro_pat_abc"
    assert loaded.token_id == "tok-1"
    assert not loaded.from_env
    assert stat.S_IMODE(_config.config_path().stat().st_mode) == 0o600
    assert not _config.has_insecure_permissions()

    _config.delete("foro.sh")
    assert _config.load("foro.sh") is None


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
