import pytest

from foro import run


class _FakeServer:
    """Records .run() kwargs instead of actually serving anything."""

    def __init__(self):
        self.run_kwargs = None

    def run(self, **kwargs):
        self.run_kwargs = kwargs


class FakeStandaloneFastMCP(_FakeServer):
    """Stands in for fastmcp.FastMCP."""


class FakeMCPServerFastMCP(_FakeServer):
    """Stands in for mcp.server.fastmcp.FastMCP."""


class FakeLowLevelServer(_FakeServer):
    """Stands in for mcp.server.lowlevel.Server."""


FLAVORS = [FakeStandaloneFastMCP, FakeMCPServerFastMCP, FakeLowLevelServer]


@pytest.mark.parametrize("server_cls", FLAVORS)
def test_run_defaults_to_port_8000_without_mcp_port(server_cls, monkeypatch):
    monkeypatch.delenv("MCP_PORT", raising=False)
    server = server_cls()

    run(server)

    assert server.run_kwargs == {
        "transport": "http",
        "host": "0.0.0.0",
        "port": 8000,
    }


@pytest.mark.parametrize("server_cls", FLAVORS)
def test_run_reads_port_from_mcp_port_env(server_cls, monkeypatch):
    monkeypatch.setenv("MCP_PORT", "9001")
    server = server_cls()

    run(server)

    assert server.run_kwargs == {
        "transport": "http",
        "host": "0.0.0.0",
        "port": 9001,
    }


def test_run_explicit_port_overrides_env(monkeypatch):
    monkeypatch.setenv("MCP_PORT", "9001")
    server = FakeStandaloneFastMCP()

    run(server, port=1234)

    assert server.run_kwargs["port"] == 1234
