"""`foro verify` - the handshake against a deployed URL.

The end-to-end case (a real server, a real session, real tool names) is
covered by test_init_dev_roundtrip, which now goes through the same
_mcp.handshake this command uses. What's left to pin here is the URL a user
actually types, and that a dead endpoint fails loudly rather than looking fine.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from typer.testing import CliRunner

from foro._mcp import HandshakeError, handshake, local_url, normalize_url
from foro.cli import app

runner = CliRunner()


@pytest.mark.parametrize(
    "raw,expected",
    [
        # What `foro deploy` prints, which is what a user has in hand.
        ("https://swift-harbor-a3f2.foro.sh", "https://swift-harbor-a3f2.foro.sh/mcp"),
        ("https://swift-harbor-a3f2.foro.sh/", "https://swift-harbor-a3f2.foro.sh/mcp"),
        # Already pointed at the endpoint - don't double it up.
        ("https://swift-harbor-a3f2.foro.sh/mcp", "https://swift-harbor-a3f2.foro.sh/mcp"),
        ("https://swift-harbor-a3f2.foro.sh/mcp/", "https://swift-harbor-a3f2.foro.sh/mcp"),
        # A bare host is https, not a relative path.
        ("swift-harbor-a3f2.foro.sh", "https://swift-harbor-a3f2.foro.sh/mcp"),
        # A dev stack is explicit about being plaintext.
        ("http://127.0.0.1:8000", "http://127.0.0.1:8000/mcp"),
        ("  https://x.foro.sh  ", "https://x.foro.sh/mcp"),
        # A path the user typed is the one they mean. Appending to anything
        # that merely didn't end in `/mcp` rewrote it: `/mcpserver` became
        # `/mcpserver/mcp`, and a server behind a path prefix could not be
        # verified at all.
        ("https://x.foro.sh/mcpserver", "https://x.foro.sh/mcpserver"),
        ("https://x.foro.sh/team/a/mcp", "https://x.foro.sh/team/a/mcp"),
        ("https://x.foro.sh/prefix/", "https://x.foro.sh/prefix"),
    ],
)
def test_url_normalisation(raw, expected):
    assert normalize_url(raw) == expected


def test_local_url_matches_what_dev_serves():
    assert local_url(8000) == "http://127.0.0.1:8000/mcp"


def test_nothing_listening_fails_with_the_url_in_the_message():
    # Port 1 is never a server; the point is a clean HandshakeError rather
    # than an ExceptionGroup from the transport reaching the user.
    with pytest.raises(HandshakeError, match="is not serving MCP"):
        handshake("http://127.0.0.1:1/mcp", timeout=5)


class _NotMcpHandler(BaseHTTPRequestHandler):
    """Answers HTTP but speaks no MCP - the shape a misconfigured route or a
    proxy error page has, and the case a plain curl would call 'up'."""

    def do_POST(self):
        body = json.dumps({"hello": "not mcp"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST

    def log_message(self, *args):
        pass


@pytest.fixture
def not_mcp():
    httpd = HTTPServer(("127.0.0.1", 0), _NotMcpHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}/mcp"
    httpd.shutdown()


def test_a_200_that_isnt_mcp_is_not_success(not_mcp):
    with pytest.raises(HandshakeError):
        handshake(not_mcp, timeout=10)


def test_cli_exits_non_zero_so_scripts_can_branch_on_it():
    result = runner.invoke(app, ["verify", "http://127.0.0.1:1", "--timeout", "5"])

    assert result.exit_code == 1
    assert "✗" in result.stdout
