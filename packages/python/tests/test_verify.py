"""URL normalisation and handshake errors for `foro verify`."""

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
        ("https://swift-harbor-a3f2.foro.sh", "https://swift-harbor-a3f2.foro.sh/mcp"),
        ("https://swift-harbor-a3f2.foro.sh/", "https://swift-harbor-a3f2.foro.sh/mcp"),
        ("https://swift-harbor-a3f2.foro.sh/mcp", "https://swift-harbor-a3f2.foro.sh/mcp"),
        ("https://swift-harbor-a3f2.foro.sh/mcp/", "https://swift-harbor-a3f2.foro.sh/mcp"),
        ("swift-harbor-a3f2.foro.sh", "https://swift-harbor-a3f2.foro.sh/mcp"),
        ("http://127.0.0.1:8000", "http://127.0.0.1:8000/mcp"),
        ("  https://x.foro.sh  ", "https://x.foro.sh/mcp"),
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
    with pytest.raises(HandshakeError, match="is not serving MCP"):
        handshake("http://127.0.0.1:1/mcp", timeout=5)


class _NotMcpHandler(BaseHTTPRequestHandler):
    """HTTP 200 that is not MCP."""

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
