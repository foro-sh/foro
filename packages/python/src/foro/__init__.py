"""The foro.sh Python SDK and CLI."""

from __future__ import annotations

import os

__all__ = ["run", "secret"]


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
