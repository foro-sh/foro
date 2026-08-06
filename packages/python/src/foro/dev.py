"""`foro dev` - run the server locally exactly as foro.sh will, then prove it
would pass the platform's health gate. "If it passes here, it passes
deployed."

Two things layered on top of each other:
  1. Start `uv run <entrypoint>` with $MCP_PORT set (matches
     Dockerfile.template's run step), then TCP-probe the port the same way
     foro-wrapper.sh's health sidecar does (a bare `socket.create_connection`,
     nothing HTTP-specific) - this is what catches the stdio-transport
     footgun `foro check` can only warn about: a server on stdio never opens
     the port, so the probe times out.
  2. Once the port's open, do a real MCP initialize handshake and list the
     server's tools - a stronger signal than the platform's own probe gives,
     but cheap to add once the port's confirmed open.
"""

from __future__ import annotations

import os
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from foro._manifest import parse_and_validate
from foro._mcp import handshake, local_url
from foro._proc import popen

DEFAULT_TIMEOUT = 60.0
POLL_INTERVAL = 0.5


class DevError(Exception):
    """The server never became healthy within the timeout."""


@dataclass
class DevResult:
    port: int
    tool_names: list[str]


def start_server(repo_dir: Path, entrypoint: str, build_path: str, port: int) -> subprocess.Popen:
    from dotenv import dotenv_values

    build_dir = repo_dir / build_path
    # A repo-root .env is a local-dev convenience only - the platform injects
    # secrets as real env vars at deploy time, never a file. Silently a no-op
    # when .env doesn't exist (dotenv_values returns {} for a missing path).
    dotenv = {k: v for k, v in dotenv_values(repo_dir / ".env").items() if v is not None}
    # FASTMCP_SHOW_SERVER_BANNER goes first so a shell export or a .env entry
    # still wins - it's a default, not a policy. This is the one place the
    # variable reliably bites: fastmcp reads it into its settings object at
    # import time, and here it's set before the child interpreter even
    # starts, which foro.run() (already inside that process) cannot do.
    env = {
        "FASTMCP_SHOW_SERVER_BANNER": "false",
        **os.environ,
        **dotenv,
        "MCP_PORT": str(port),
    }
    return popen(
        ["uv", "run", entrypoint],
        cwd=build_dir,
        env=env,
        stdin=subprocess.DEVNULL,
    )


def port_is_open(port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_for_port(
    port: int, timeout: float = DEFAULT_TIMEOUT, process: subprocess.Popen | None = None
) -> bool:
    """Wait for something to accept a TCP connection on `port`.

    Pass `process` to stop waiting on a server that has already died. Without
    it this polls the full timeout no matter what - a server that exits in
    half a second still cost 60 seconds before `foro dev` said anything.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            return False
        if port_is_open(port, timeout=2):
            return True
        time.sleep(POLL_INTERVAL)
    return False


# A stdio server under `foro dev` doesn't hang with the port closed - it gets
# DEVNULL for stdin, reads EOF, and exits at once. So "exited immediately" and
# "never opened the port" are two faces of the same footgun, and the hint
# belongs on both.
_STDIO_HINT = (
    "If the entrypoint calls a plain server.run() / mcp.run(), that defaults to "
    "stdio transport, which never opens a port and would fail foro.sh's deploy "
    "health check the same way - call foro.run(server) instead."
)


def _unhealthy_reason(process: subprocess.Popen, port: int, timeout: float) -> str:
    status = process.poll()
    if status is not None:
        # The child inherits this process's stdout and stderr, so whatever it
        # said on the way out is already on screen. Naming the exit status and
        # pointing at that output beats guessing at a cause the traceback
        # right above may well state outright.
        return (
            f"the server exited with status {status} without opening port {port} - "
            f"its output is above. {_STDIO_HINT}"
        )
    return f"server never opened port {port} within {timeout:.0f}s. {_STDIO_HINT}"


def mcp_handshake(port: int) -> list[str]:
    """The same handshake `foro verify` runs against a deployed URL - see
    _mcp.py, which owns it so the two can't disagree about what working means."""
    return handshake(local_url(port))


def run_dev(repo_dir: Path | str, timeout: float = DEFAULT_TIMEOUT) -> tuple[subprocess.Popen, DevResult]:
    """Start the repo's server and verify it would pass foro.sh's deploy
    health gate. Returns the running process (caller owns its lifecycle -
    terminate it when done) plus the verified port and tool list. Raises
    DevError if the server dies or the port never opens in time; the process
    is cleaned up before raising.
    """
    repo_dir = Path(repo_dir)
    manifest = parse_and_validate(repo_dir, ".")

    # Claim the port before starting, because afterwards there is no way to
    # tell whose listener the probe found. A stale `foro dev`, another project
    # on 8000, anything - the connection succeeds either way, and dev would
    # report a healthy server while the one it just started was already dead.
    # Checking first turns a false green into the actual problem.
    if port_is_open(manifest.port):
        raise DevError(
            f"port {manifest.port} is already in use - something else is listening on "
            "it, so foro dev cannot tell its server apart from that one. Stop it, or "
            "give this project a different `port:` in foro.yaml."
        )

    process = start_server(repo_dir, manifest.entrypoint, manifest.build_path, manifest.port)
    try:
        if not wait_for_port(manifest.port, timeout=timeout, process=process):
            raise DevError(_unhealthy_reason(process, manifest.port, timeout))
        tool_names = mcp_handshake(manifest.port)
    except Exception:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        raise

    return process, DevResult(port=manifest.port, tool_names=tool_names)
