"""The foro.sh Python SDK and CLI."""

from __future__ import annotations

import os
import sys

__all__ = ["run", "secret", "bridge"]

# Same art as platform:infra/templates/foro-wrapper.sh. Duplicated because
# nothing links the two repos at runtime.
_BANNER = """
███████╗ ██████╗ ██████╗  ██████╗
██╔════╝██╔═══██╗██╔══██╗██╔═══██╗
█████╗  ██║   ██║██████╔╝██║   ██║
██╔══╝  ██║   ██║██╔══██╗██║   ██║
██║     ╚██████╔╝██║  ██║╚██████╔╝
╚═╝      ╚═════╝ ╚═╝  ╚═╝ ╚═════╝
"""


def _show_foro_banner(port: int) -> None:
    # PROJECT_SLUG is set only in platform-created containers, where the
    # wrapper already printed this banner before exec.
    if os.environ.get("PROJECT_SLUG"):
        return
    print(_BANNER.strip("\n"))
    print(f"foro.sh · MCP server starting on port {port}\n", flush=True)


def _accepts_show_banner(run_method) -> bool:
    # A **kwargs catch-all does not count: the server would forward
    # show_banner to a transport that rejects it. Signature-check, not
    # try/except TypeError: the server runs inside the call, so a later
    # TypeError from a tool would look like a rejected argument.
    import inspect

    try:
        return "show_banner" in inspect.signature(run_method).parameters
    except (TypeError, ValueError):
        return False


def _resolve_port(port: int | None) -> int:
    if port is None:
        raw = os.environ.get("PORT", "8000")
        try:
            port = int(raw)
        except ValueError:
            raise ValueError(f"PORT is not a number: {raw!r}") from None

    # 0 binds an OS-assigned port. The health probe checks the declared port.
    if not 1 <= port <= 65535:
        raise ValueError(f"port must be between 1 and 65535, got {port}")
    return port


def run(server, *, port: int | None = None) -> None:
    """Run an MCP server over streamable HTTP on 0.0.0.0:$PORT.

    Accepts any FastMCP-shaped object with a compatible .run().
    """
    resolved_port = _resolve_port(port)

    # fastmcp reads this at import time. Set it for processes that import
    # fastmcp after this call (bridge backends, user-spawned tools).
    # show_banner below is what suppresses this process's banner.
    os.environ.setdefault("FASTMCP_SHOW_SERVER_BANNER", "false")

    _show_foro_banner(resolved_port)

    kwargs = {"transport": "http", "host": "0.0.0.0", "port": resolved_port}
    if _accepts_show_banner(server.run):
        kwargs["show_banner"] = False
    server.run(**kwargs)


def secret(name: str) -> str:
    """Read a required secret from the environment.

    Raises RuntimeError instead of KeyError.
    """
    try:
        return os.environ[name]
    except KeyError:
        raise RuntimeError(
            f"Secret {name!r} is not set. Add it in your project's "
            f"Secrets tab in the foro.sh dashboard."
        ) from None


def bridge(command: list[str], *, port: int | None = None, shared: bool = False) -> None:
    """Proxy a stdio MCP server over streamable HTTP.

    `command` is argv for the backend. Default: one backend process per HTTP
    session. shared=True reuses one process across sessions.

    Runs the backend's MCP initialize handshake before serving. foro.sh's
    health probe only checks that this process opened $PORT.
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

    # The container PYTHONPATH points at foro.sh's sitecustomize.py metrics
    # shim. If the child is a FastMCP server, that shim writes metric lines
    # to stdout, which is the child's JSON-RPC channel.
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
