"""Filesystem-dependent check-only rules, exercised against whole miniature
repos under tests/fixtures/<name>/ - the cases manifest-cases.json can't
express because they turn on files on disk, not just foro.yaml content.

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


def test_ts_project_fails_as_unsupported_language():
    result = run_check(FIXTURES / "ts-project")

    assert not result.ok
    assert result.reason == "unsupported_language"


def test_wrong_fastmcp_import_warns_but_passes():
    result = run_check(FIXTURES / "wrong-fastmcp-import")

    assert result.ok
    assert len(result.warnings) == 1
    assert "mcp.server.fastmcp" in result.warnings[0]
