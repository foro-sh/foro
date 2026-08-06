"""The foro.sh Python SDK and CLI."""

from __future__ import annotations

import os
import sys

__all__ = ["run", "secret", "bridge"]

# The same art the platform's container wrapper prints
# (platform:infra/templates/foro-wrapper.sh), duplicated rather than shared
# because nothing links the two repos at runtime - a deployed container runs
# the wrapper, `foro dev` runs this. Keep them in step by eye.
_BANNER = """
███████╗ ██████╗ ██████╗  ██████╗
██╔════╝██╔═══██╗██╔══██╗██╔═══██╗
█████╗  ██║   ██║██████╔╝██║   ██║
██╔══╝  ██║   ██║██╔══██╗██║   ██║
██║     ╚██████╔╝██║  ██║╚██████╔╝
╚═╝      ╚═════╝ ╚═╝  ╚═╝ ╚═════╝
"""


def _show_foro_banner(port: int) -> None:
    """Print foro's startup banner in place of FastMCP's own, which
    advertises a third-party deploy target to people already deployed on
    foro.sh.

    Skipped inside a deployed container: the wrapper script prints this
    exact art before exec'ing the server, so printing again would double it
    in the runtime log tab. PROJECT_SLUG is the marker - the platform
    injects it into every container it creates and nothing else sets it.
    """
    if os.environ.get("PROJECT_SLUG"):
        return
    print(_BANNER.strip("\n"))
    print(f"foro.sh · MCP server starting on port {port}\n", flush=True)


def _accepts_show_banner(run_method) -> bool:
    """Whether `run_method` takes an explicit `show_banner`. Deliberately
    does not count a **kwargs catch-all: a server that forwards unknown
    keywords to its transport would turn a suppression attempt into a
    TypeError from somewhere unrelated. Signature-checking rather than
    try/except TypeError for the same reason - the server runs inside that
    call, so a TypeError raised by a tool hours later would otherwise look
    like a rejected argument and silently restart the server."""
    import inspect

    try:
        return "show_banner" in inspect.signature(run_method).parameters
    except (TypeError, ValueError):  # C-implemented or otherwise unintrospectable
        return False


def _resolve_port(port: int | None) -> int:
    """The port to bind, from the explicit argument or $MCP_PORT.

    Resolved on `is None`: `port or ...` read an explicit 0 as "not given".
    """
    if port is None:
        raw = os.environ.get("MCP_PORT", "8000")
        try:
            port = int(raw)
        except ValueError:
            raise ValueError(f"MCP_PORT is not a number: {raw!r}") from None

    # 0 binds whatever the OS hands out, but the health probe checks the port
    # the manifest declared - a random one fails the deploy confusingly.
    if not 1 <= port <= 65535:
        raise ValueError(f"port must be between 1 and 65535, got {port}")
    return port


def run(server, *, port: int | None = None) -> None:
    """Run an MCP server the way foro.sh expects: streamable HTTP, bound on
    all interfaces, on $MCP_PORT. Identical locally and deployed.

    Accepts any FastMCP-shaped server (standalone fastmcp.FastMCP,
    mcp.server.fastmcp.FastMCP, or a low-level Server) - it's duck-typed, not
    checked against a specific class, so it just needs a compatible .run().
    """
    resolved_port = _resolve_port(port)

    # Only reaches a FastMCP imported after this point - fastmcp reads the
    # variable into its settings object at import time, and by the time a
    # server instance gets here that import has long happened. It's set
    # anyway for the processes downstream of us that import fastmcp late:
    # `foro.bridge` proxy backends, and anything the user's tools spawn.
    # `show_banner` below is what actually suppresses this process's banner.
    os.environ.setdefault("FASTMCP_SHOW_SERVER_BANNER", "false")

    _show_foro_banner(resolved_port)

    kwargs = {"transport": "http", "host": "0.0.0.0", "port": resolved_port}
    if _accepts_show_banner(server.run):
        kwargs["show_banner"] = False
    server.run(**kwargs)


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
