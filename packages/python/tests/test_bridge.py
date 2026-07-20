import asyncio
import sys
from pathlib import Path

import pytest

from foro import _backend_transport, _check_backend, bridge

_BACKEND_SCRIPT = '''\
from fastmcp import FastMCP

mcp = FastMCP("backend")


@mcp.tool
def add(a: int, b: int) -> int:
    return a + b


if __name__ == "__main__":
    mcp.run()
'''


@pytest.fixture
def backend_script(tmp_path: Path) -> Path:
    script = tmp_path / "backend.py"
    script.write_text(_BACKEND_SCRIPT)
    return script


def test_backend_transport_strips_pythonpath_keeps_rest_of_env(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "/platform/metrics-shim")
    monkeypatch.setenv("SOME_SECRET", "shh")

    transport = _backend_transport(["node", "server.js"], shared=False)

    assert transport.command == "node"
    assert transport.args == ["server.js"]
    assert "PYTHONPATH" not in transport.env
    assert transport.env["SOME_SECRET"] == "shh"


def test_backend_transport_pipes_stderr_to_our_stdout():
    transport = _backend_transport(["node", "server.js"], shared=False)

    assert transport.log_file is sys.stdout


def test_backend_transport_default_is_fresh_process_per_session():
    transport = _backend_transport(["node", "server.js"], shared=False)

    assert transport.keep_alive is False


def test_backend_transport_shared_keeps_one_process():
    transport = _backend_transport(["node", "server.js"], shared=True)

    assert transport.keep_alive is True


def test_bridge_raises_when_backend_cannot_start():
    with pytest.raises(RuntimeError, match=r"foro\.bridge"):
        bridge(["python3", "-c", "import sys; sys.exit(1)"])


def test_check_backend_succeeds_against_a_real_stdio_server(backend_script):
    transport = _backend_transport([sys.executable, str(backend_script)], shared=False)

    asyncio.run(_check_backend(transport))


def test_bridge_proxy_serves_backend_tools(backend_script):
    from fastmcp import Client
    from fastmcp.server import create_proxy

    transport = _backend_transport([sys.executable, str(backend_script)], shared=False)
    asyncio.run(_check_backend(transport))  # the eager health-gate check bridge() itself does

    proxy = create_proxy(transport, name="foro-bridge")

    async def call_add():
        async with Client(proxy) as client:
            tools = await client.list_tools()
            result = await client.call_tool("add", {"a": 2, "b": 3})
            return [tool.name for tool in tools], result.data

    tool_names, result = asyncio.run(call_add())

    assert tool_names == ["add"]
    assert result == 5
