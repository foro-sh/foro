"""MCP initialize + list_tools, used by `foro dev` and `foro verify`."""

from __future__ import annotations

import sys
import urllib.parse

if sys.version_info < (3, 11):
    # BaseExceptionGroup is builtin from 3.11. anyio's task group raises the
    # exceptiongroup backport below that; the bare name is a NameError on 3.10.
    from exceptiongroup import BaseExceptionGroup

DEFAULT_TIMEOUT = 30.0


class HandshakeError(Exception):
    pass


async def _handshake(url: str, timeout: float) -> list[str]:
    import anyio

    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    with anyio.fail_after(timeout):
        async with streamable_http_client(url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return [tool.name for tool in result.tools]


def handshake(url: str, timeout: float = DEFAULT_TIMEOUT) -> list[str]:
    import anyio

    try:
        return anyio.run(_handshake, url, timeout)
    except TimeoutError:
        raise HandshakeError(f"{url} did not answer within {timeout:.0f}s") from None
    except Exception as err:
        raise HandshakeError(f"{url} is not serving MCP: {_root_cause(err)}") from None


def _root_cause(err: BaseException) -> str:
    while isinstance(err, BaseExceptionGroup) and err.exceptions:
        err = err.exceptions[0]
    return f"{type(err).__name__}: {err}" if str(err) else type(err).__name__


def local_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/mcp"


def normalize_url(raw: str) -> str:
    url = raw.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    parts = urllib.parse.urlsplit(url)
    if parts.path in ("", "/"):
        return urllib.parse.urlunsplit(parts._replace(path="/mcp"))
    return url
