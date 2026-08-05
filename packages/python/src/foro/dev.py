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
    env = {**os.environ, **dotenv, "MCP_PORT": str(port)}
    return subprocess.Popen(
        ["uv", "run", entrypoint],
        cwd=build_dir,
        env=env,
        stdin=subprocess.DEVNULL,
    )


def wait_for_port(port: int, timeout: float = DEFAULT_TIMEOUT) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2):
                return True
        except OSError:
            time.sleep(POLL_INTERVAL)
    return False


def mcp_handshake(port: int) -> list[str]:
    """The same handshake `foro verify` runs against a deployed URL - see
    _mcp.py, which owns it so the two can't disagree about what working means."""
    return handshake(local_url(port))


def stop(process: subprocess.Popen) -> None:
    """Shut down a server started by `run_dev`, escalating to a kill if it
    doesn't go quietly. Everything holding one of these processes needs this
    same sequence - the CLI on Ctrl+C and under `--once`, run_dev itself when
    verification fails, and the tests - so it lives here once."""
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def run_dev(repo_dir: Path | str, timeout: float = DEFAULT_TIMEOUT) -> tuple[subprocess.Popen, DevResult]:
    """Start the repo's server and verify it would pass foro.sh's deploy
    health gate. Returns the running process (caller owns its lifecycle -
    `stop()` it when done) plus the verified port and tool list. Raises
    DevError if the port never opens in time; the process is cleaned up
    before raising.
    """
    repo_dir = Path(repo_dir)
    manifest = parse_and_validate(repo_dir, ".")

    process = start_server(repo_dir, manifest.entrypoint, manifest.build_path, manifest.port)
    try:
        if not wait_for_port(manifest.port, timeout=timeout):
            raise DevError(
                f"server never opened port {manifest.port} within {timeout:.0f}s - "
                "does the entrypoint call foro.run(server)? A plain server.run() / "
                "mcp.run() defaults to stdio transport, which never opens a port and "
                "would fail foro.sh's deploy health check the same way."
            )
        tool_names = mcp_handshake(manifest.port)
    except Exception:
        stop(process)
        raise

    return process, DevResult(port=manifest.port, tool_names=tool_names)
