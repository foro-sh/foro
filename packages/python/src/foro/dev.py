"""Run the server locally the way foro.sh will, then TCP-probe and handshake."""

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
    pass


@dataclass
class DevResult:
    port: int
    tool_names: list[str]


def start_server(repo_dir: Path, entrypoint: str, build_path: str, port: int) -> subprocess.Popen:
    from dotenv import dotenv_values

    build_dir = repo_dir / build_path
    dotenv = {k: v for k, v in dotenv_values(repo_dir / ".env").items() if v is not None}
    # FASTMCP_SHOW_SERVER_BANNER is read at import time. Set it in the child
    # env before the interpreter starts. A shell export or .env entry wins.
    env = {
        "FASTMCP_SHOW_SERVER_BANNER": "false",
        **os.environ,
        **dotenv,
        # Last so the manifest port wins over PORT in .env.
        "PORT": str(port),
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
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            return False
        if port_is_open(port, timeout=2):
            return True
        time.sleep(POLL_INTERVAL)
    return False


_STDIO_HINT = (
    "If the entrypoint calls a plain server.run() / mcp.run(), that defaults to "
    "stdio transport, which never opens a port and would fail foro.sh's deploy "
    "health check the same way - call foro.run(server) instead."
)


def _unhealthy_reason(process: subprocess.Popen, port: int, timeout: float) -> str:
    status = process.poll()
    if status is not None:
        return (
            f"the server exited with status {status} without opening port {port} - "
            f"its output is above. {_STDIO_HINT}"
        )
    return f"server never opened port {port} within {timeout:.0f}s. {_STDIO_HINT}"


def mcp_handshake(port: int) -> list[str]:
    return handshake(local_url(port))


def stop(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def run_dev(repo_dir: Path | str, timeout: float = DEFAULT_TIMEOUT) -> tuple[subprocess.Popen, DevResult]:
    repo_dir = Path(repo_dir)
    manifest = parse_and_validate(repo_dir, ".")

    if port_is_open(manifest.port):
        raise DevError(
            f"port {manifest.port} is already in use - something else is listening on "
            "it, so foro dev cannot tell its server apart from that one. Stop it, or "
            "give this project a different `port` in its [tool.foro] table."
        )

    process = start_server(repo_dir, manifest.entrypoint, manifest.build_path, manifest.port)
    try:
        if not wait_for_port(manifest.port, timeout=timeout, process=process):
            raise DevError(_unhealthy_reason(process, manifest.port, timeout))
        tool_names = mcp_handshake(manifest.port)
    except Exception:
        stop(process)
        raise

    return process, DevResult(port=manifest.port, tool_names=tool_names)
