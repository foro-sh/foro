"""Filesystem-dependent check-only rules, exercised against whole miniature
repos under tests/fixtures/<name>/ - the cases manifest-cases.json can't
express because they turn on files on disk, not just config-file content.

Not every fixture from foro-sh/foro#5's original table is here: build-path-subdir,
with-secrets, stdio-one-line, and bridge-stdio don't add coverage of check()
that minimal-fastmcp doesn't already provide (check never executes the
entrypoint), and bridge-stdio's premise depends on foro.bridge() (#8, not
built yet). stdio-only is dynamic-only (needs `foro dev`, #7) - check can't
catch it statically. Left as follow-up, not invented here.
"""

from __future__ import annotations

from pathlib import Path

from foro.check import run_check

FIXTURES = Path(__file__).parent / "fixtures"


def test_minimal_fastmcp_passes_clean():
    result = run_check(FIXTURES / "minimal-fastmcp")

    assert result.ok
    assert result.warnings == []


def test_missing_lockfile_warns_but_passes():
    # Corrected from foro-sh/foro#1's original fixture table, which expected
    # this to be a hard "missing_lockfile" rejection: python-project.ts
    # actually falls back to an unlocked `uv sync` when uv.lock is absent, so
    # the platform accepts this - check must agree, or it lies about a repo
    # that would in fact deploy.
    result = run_check(FIXTURES / "missing-lockfile")

    assert result.ok
    assert len(result.warnings) == 1
    assert "uv.lock" in result.warnings[0]


def test_lockfile_out_of_sync_fails():
    result = run_check(FIXTURES / "lockfile-out-of-sync")

    assert not result.ok
    assert result.reason == "lockfile_out_of_sync"


def test_entrypoint_missing_fails():
    result = run_check(FIXTURES / "entrypoint-missing")

    assert not result.ok
    assert result.reason == "entrypoint_file_missing"


def test_no_manifest_fails():
    result = run_check(FIXTURES / "no-manifest")

    assert not result.ok
    assert result.reason == "missing_manifest"


def test_node_project_passes():
    result = run_check(FIXTURES / "node-minimal")

    assert result.ok
    assert result.warnings == []


def test_node_project_without_an_entry_file_fails():
    # A package.json with no `main`, no `bin` and no index.js beside it: the
    # runtime is unambiguous, the file to start is not.
    result = run_check(FIXTURES / "node-no-entry")

    assert not result.ok
    assert result.reason == "invalid_entrypoint"


def test_node_project_under_a_python_build_path_is_told_which_field_to_set(tmp_path):
    # `build_path` can point the build somewhere the config file isn't, so a
    # Python project can still send the detector into a Node directory.
    # Listing the Python markers it lacks would be honest and useless; naming
    # the field is the actual fix.
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "my-server"\n\n[tool.foro]\n'
        'entrypoint = "dist/index.js"\nbuild_path = "app"\n'
    )
    (tmp_path / "app" / "dist").mkdir(parents=True)
    (tmp_path / "app" / "dist" / "index.js").write_text("")
    (tmp_path / "app" / "package.json").write_text('{"name": "my-server"}\n')

    result = run_check(tmp_path)

    assert not result.ok
    assert result.reason == "unsupported_project"
    assert "runtime" in result.message


def test_wrong_fastmcp_import_warns_but_passes():
    result = run_check(FIXTURES / "wrong-fastmcp-import")

    assert result.ok
    assert len(result.warnings) == 1
    assert "mcp.server.fastmcp" in result.warnings[0]


def test_wrong_fastmcp_import_detected_outside_entrypoint(tmp_path):
    # The recommended structure (foro init's own scaffold) puts FastMCP
    # construction in app.py, imported by the entrypoint - the wrong-import
    # scan has to look beyond just the entrypoint file or this regresses
    # silently for exactly the layout foro init itself now produces.
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "split-server"\n')
    (tmp_path / "app.py").write_text(
        'from mcp.server.fastmcp import FastMCP\nmcp = FastMCP("x")\n'
    )
    (tmp_path / "server.py").write_text("import foro\nfrom app import mcp\n\nforo.run(mcp)\n")

    result = run_check(tmp_path)

    assert result.ok
    assert any("app.py" in w and "mcp.server.fastmcp" in w for w in result.warnings)


_MARKER = "from mcp.server.fastmcp import FastMCP\n"


def _project(tmp_path):
    (tmp_path / "server.py").write_text("import foro\n")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "my-server"\n')
    return tmp_path


def test_the_wrong_import_is_still_found_in_the_users_own_code(tmp_path):
    _project(tmp_path)
    (tmp_path / "app.py").write_text(_MARKER)

    assert any("app.py" in w for w in run_check(tmp_path).warnings)


def test_vendored_and_hidden_directories_are_not_scanned(tmp_path):
    """Only .venv/__pycache__/.git were skipped, so .tox, node_modules and
    site-packages all false-positived."""
    _project(tmp_path)
    for buried in (
        ".tox/py312/lib/python3.12/site-packages/mcp/server/x.py",
        "node_modules/thing/y.py",
        ".venv/lib/site-packages/fastmcp/z.py",
        "tests/test_imports.py",
    ):
        target = tmp_path / buried
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_MARKER)

    assert not [w for w in run_check(tmp_path).warnings if "mcp.server.fastmcp" in w]
