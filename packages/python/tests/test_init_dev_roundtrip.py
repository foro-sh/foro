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
from foro.dev import run_dev

runner = CliRunner()

_PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def test_init_output_passes_check_and_serves_via_dev(tmp_path):
    target = tmp_path / "roundtrip-server"

    result = runner.invoke(app, ["init", str(target)], input="\n\n\n\nn\n")
    assert result.exit_code == 0, result.stdout

    check_result = run_check(target)
    assert check_result.ok, check_result.message

    # Test-only fixup: point the scaffold's `foro` dependency at this repo's
    # own package instead of PyPI (foro-sh/foro#6/#7's PR description covers
    # why - the published package predates foro.run/foro.secret). A real
    # `foro init` output depends on published foro, as it should; only the
    # test needs to dodge that staleness to actually execute the entrypoint.
    with open(target / "pyproject.toml", "a") as f:
        f.write(f'\n[tool.uv.sources]\nforo = {{ path = "{_PACKAGE_ROOT}", editable = true }}\n')
    subprocess.run(["uv", "lock"], cwd=target, check=True, capture_output=True)

    # A tool file dropped in after scaffolding has to be served without
    # touching any other file - that's the whole point of load_tools()
    # discovering modules instead of tools/__init__.py listing them. The
    # underscore-prefixed neighbour must stay unimported: it's the escape
    # hatch for shared helpers, and importing it would raise.
    (target / "tools" / "echo.py").write_text(
        'from app import mcp\n\n\n@mcp.tool\ndef echo(text: str) -> str:\n    return text\n'
    )
    (target / "tools" / "_helpers.py").write_text('raise AssertionError("private module was imported")\n')

    process, dev_result = run_dev(target, timeout=30)
    try:
        assert "add" in dev_result.tool_names
        assert "echo" in dev_result.tool_names
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
