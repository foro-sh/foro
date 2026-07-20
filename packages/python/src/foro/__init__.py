"""The foro.sh Python SDK and CLI."""

from __future__ import annotations

import os
import sys

__all__ = ["run", "secret", "bridge"]


def run(server, *, port: int | None = None) -> None:
    """Run an MCP server the way foro.sh expects: streamable HTTP, bound on
    all interfaces, on $MCP_PORT. Identical locally and deployed.

    Accepts any FastMCP-shaped server (standalone fastmcp.FastMCP,
    mcp.server.fastmcp.FastMCP, or a low-level Server) - it's duck-typed, not
    checked against a specific class, so it just needs a compatible .run().
    """
    server.run(
        transport="http",
        host="0.0.0.0",
        port=port or int(os.environ.get("MCP_PORT", "8000")),
    )


def secret(name: str) -> str:
    """Read a required secret from the environment.

    Raises a dashboard-actionable error instead of a bare KeyError.
    """
    try:
        return os.environ[name]
    except KeyError:
        raise RuntimeError(
            f"Secret {name!r} is not set. Add it in your project's "
            f"Secrets tab in the foro.sh dashboard."
        ) from None


def bridge(command: list[str], *, port: int | None = None, shared: bool = False) -> None:
    """Proxy an opaque stdio MCP server - third-party or non-Python, anything
    you can't just import and hand to `run()` - over the streamable-HTTP
    transport foro.sh requires, without hand-rolling a JSON-RPC pump.

    `command` is argv for the backend, e.g. ["uvx", "some-stdio-mcp"] or
    ["node", "server.js"]. Stdio is inherently single-client, so by default
    every HTTP session gets its own fresh backend subprocess (isolation);
    pass shared=True to reuse one process across every session instead -
    only correct for a backend with no per-client state.

    Eagerly performs the backend's MCP initialize handshake before serving
    and raises if it fails. foro.sh's health probe only checks that this
    process opened $MCP_PORT, not that the backend actually works - a
    backend that dies on a bad import would otherwise report healthy while
    every tool call fails.
    """
    import asyncio

    from fastmcp.server import create_proxy

    backend = _backend_transport(command, shared=shared)

    try:
        asyncio.run(_check_backend(backend))
    except Exception as error:
        raise RuntimeError(
            f"foro.bridge: backend {command!r} failed to start or respond "
            f"to the MCP initialize handshake: {error}"
        ) from error

    run(create_proxy(backend, name="foro-bridge"), port=port)


def _backend_transport(command: list[str], *, shared: bool):
    from fastmcp.client.transports import StdioTransport

    # The container's PYTHONPATH points at foro.sh's sitecustomize.py metrics
    # shim, which the child would otherwise inherit. If the child is itself
    # a FastMCP server, that shim prints a metric line to stdout per tool
    # call - but the child's stdout is its JSON-RPC channel to us, so that
    # can corrupt the protocol. Metrics still work without it: the proxy
    # front (this process) is a fastmcp.FastMCP the shim already patches,
    # and forwarded tool calls run through its own on_call_tool.
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)

    return StdioTransport(
        command[0],
        args=list(command[1:]),
        env=env,
        keep_alive=shared,
        log_file=sys.stdout,
    )


async def _check_backend(transport) -> None:
    from fastmcp import Client

    async with Client(transport):
        pass
