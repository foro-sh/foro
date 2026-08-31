"""One MCP handshake, used against both a local `foro dev` server and a
deployed URL.

`foro dev` established the standard: don't report a server as working because
it printed a banner - open a session and list its tools. `foro verify` applies
the same standard to a deployed server, where a green deploy only means the
container passed a TCP probe. Same code, different target, so the two can't
drift into disagreeing about what "working" means.
"""

from __future__ import annotations

import sys
import urllib.parse

if sys.version_info < (3, 11):
    # `BaseExceptionGroup` is a builtin only from 3.11. Below that the group
    # anyio's task group raises is the `exceptiongroup` backport's, and the
    # bare builtin name in _root_cause is a NameError - which turned every
    # failed handshake on 3.10 into a traceback instead of a HandshakeError,
    # on a floor pyproject.toml declares as supported.
    from exceptiongroup import BaseExceptionGroup

# A deployed server is a network round trip away and may be cold-starting;
# generous enough for that, short enough that a hung endpoint still fails.
DEFAULT_TIMEOUT = 30.0


class HandshakeError(Exception):
    """The endpoint didn't complete an MCP handshake, with the reason why."""


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
    """Initialize an MCP session against `url` and return its tool names.

    Raises HandshakeError with a message worth showing rather than letting an
    ExceptionGroup from the transport reach the user.
    """
    import anyio

    try:
        return anyio.run(_handshake, url, timeout)
    except TimeoutError:
        raise HandshakeError(f"{url} did not answer within {timeout:.0f}s") from None
    except Exception as err:
        # The streamable-HTTP client raises through a task group, so the
        # useful cause is usually nested one or more levels down.
        raise HandshakeError(f"{url} is not serving MCP: {_root_cause(err)}") from None


def _root_cause(err: BaseException) -> str:
    while isinstance(err, BaseExceptionGroup) and err.exceptions:
        err = err.exceptions[0]
    return f"{type(err).__name__}: {err}" if str(err) else type(err).__name__


def local_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/mcp"


def normalize_url(raw: str) -> str:
    """Accept what a user actually has in hand - the URL `foro deploy` printed
    (`https://<slug>.foro.sh`) - and point it at the MCP path.

    Only a URL with no path of its own gets `/mcp` appended - a path that is
    already there is the one the user means.
    """
    url = raw.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    parts = urllib.parse.urlsplit(url)
    if parts.path in ("", "/"):
        return urllib.parse.urlunsplit(parts._replace(path="/mcp"))
    return url
