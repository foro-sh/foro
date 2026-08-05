"""The golden round-trip from foro-sh/foro#1's original test plan: init's
output must pass check, and must actually serve when run through dev. The
scaffolder can't emit something the rest of the toolchain would reject.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from typer.testing import CliRunner

from foro.check import run_check
from foro.cli import app
from foro.dev import run_dev, stop

runner = CliRunner()

_PACKAGE_ROOT = Path(__file__).resolve().parent.parent

_BACKEND_SCRIPT = '''\
from fastmcp import FastMCP

mcp = FastMCP("backend")


@mcp.tool
def echo(text: str) -> str:
    return text


if __name__ == "__main__":
    mcp.run()
'''


def _use_local_foro(target: Path) -> None:
    """Test-only fixup: point the scaffold's `foro` dependency at this repo's
    own package instead of PyPI (foro-sh/foro#6/#7's PR description covers
    why - the published package predates foro.run/foro.secret). A real
    `foro init` output depends on published foro, as it should; only the test
    needs to dodge that staleness to actually execute the entrypoint."""
    with open(target / "pyproject.toml", "a") as f:
        f.write(f'\n[tool.uv.sources]\nforo = {{ path = "{_PACKAGE_ROOT}", editable = true }}\n')
    subprocess.run(["uv", "lock"], cwd=target, check=True, capture_output=True)


def test_init_output_passes_check_and_serves_via_dev(tmp_path):
    target = tmp_path / "roundtrip-server"

    result = runner.invoke(app, ["init", str(target)], input="\n\n\n\nn\n")
    assert result.exit_code == 0, result.stdout

    check_result = run_check(target)
    assert check_result.ok, check_result.message

    _use_local_foro(target)

    process, dev_result = run_dev(target, timeout=30)
    try:
        assert "add" in dev_result.tool_names
    finally:
        stop(process)


def test_bridge_init_output_serves_the_backends_tools(tmp_path):
    """The same round-trip for `--bridge`, and the only thing that proves the
    scaffold is wired correctly end to end: the tools `dev` lists have to come
    from the backend process, since a bridge project defines none of its own.

    The backend is a local script rather than a real `uvx some-server` so the
    test doesn't depend on a third-party package staying published. Under
    `uv run`, `python` resolves inside the scaffolded project's own venv -
    where fastmcp is installed - which is the same shape a real backend has.
    """
    target = tmp_path / "roundtrip-bridge"

    result = runner.invoke(app, ["init", str(target), "--yes", "--bridge", "python backend.py"])
    assert result.exit_code == 0, result.stdout

    (target / "backend.py").write_text(_BACKEND_SCRIPT)
    check_result = run_check(target)
    assert check_result.ok, check_result.message

    _use_local_foro(target)

    process, dev_result = run_dev(target, timeout=30)
    try:
        assert dev_result.tool_names == ["echo"]
    finally:
        stop(process)
