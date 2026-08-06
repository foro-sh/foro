"""What happens when `uv` or `git` isn't installed - `foro` is documented as
`pip install`-able, which brings neither.

Each site answers it differently, and the difference is the point: `dev`
cannot run without uv, `check` can validate everything but the lockfile, and
a scaffolded project is fine without being a git repo.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from foro import _proc
from foro.check import run_check
from foro.cli import app
from foro.dev import run_dev
from foro.init import GitInitError, ManifestFields, ScaffoldError, init_git_repo, scaffold_new

runner = CliRunner()


@pytest.fixture
def without(monkeypatch):
    """Hide named binaries only - emptying PATH takes too much with it."""

    def hide(*tools: str) -> None:
        real_run, real_popen = subprocess.run, subprocess.Popen

        def guard(real):
            def wrapper(argv, *args, **kwargs):
                if argv and argv[0] in tools:
                    raise FileNotFoundError(2, "No such file or directory", argv[0])
                return real(argv, *args, **kwargs)

            return wrapper

        monkeypatch.setattr(subprocess, "run", guard(real_run))
        monkeypatch.setattr(subprocess, "Popen", guard(real_popen))

    return hide


def _project(tmp_path: Path) -> Path:
    (tmp_path / "foro.yaml").write_text("name: my-server\nentrypoint: server.py\n")
    (tmp_path / "server.py").write_text("# mcp server\n")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "my-server"\n')
    (tmp_path / "uv.lock").write_text("version = 1\n")
    return tmp_path


def test_check_still_passes_without_uv_but_says_the_lockfile_went_unchecked(tmp_path, without):
    without("uv")

    result = run_check(_project(tmp_path))

    # Everything check does that doesn't need uv still ran, so the verdict
    # stands - but it must not read as "uv.lock is fine".
    assert result.ok
    assert any("not installed" in w and "uv.lock was not checked" in w for w in result.warnings)


def test_check_cli_prints_the_warning_and_exits_zero(tmp_path, without):
    without("uv")

    result = runner.invoke(app, ["check", str(_project(tmp_path))])

    assert result.exit_code == 0
    assert "warning:" in result.stdout
    assert "docs.astral.sh/uv" in result.stdout


def test_dev_without_uv_names_uv_rather_than_an_errno(tmp_path, without):
    without("uv")

    result = runner.invoke(app, ["dev", str(_project(tmp_path))])

    assert result.exit_code == 1
    assert "`uv` is not installed" in result.stdout
    assert "FileNotFoundError" not in result.stdout


def test_run_dev_raises_a_typed_error_rather_than_oserror(tmp_path, without):
    without("uv")

    with pytest.raises(_proc.MissingToolError):
        run_dev(_project(tmp_path))


def test_scaffold_without_uv_leaves_nothing_behind(tmp_path, without):
    """The retry matters more than the message: `foro init <name>` refuses a
    non-empty target, so the leftovers blocked the next command."""
    without("uv")
    target = tmp_path / "scaffolded"

    with pytest.raises(ScaffoldError, match="not installed"):
        scaffold_new(target, ManifestFields(name="scaffolded", entrypoint="server.py"))

    assert not target.exists()


def test_scaffold_takes_back_only_its_own_files_when_the_target_pre_existed(tmp_path, without):
    without("uv")
    target = tmp_path / "mine"
    target.mkdir()
    (target / "NOTES.md").write_text("not foro's to delete\n")

    with pytest.raises(ScaffoldError):
        scaffold_new(target, ManifestFields(name="mine", entrypoint="server.py"))

    assert target.is_dir()
    assert [p.name for p in target.iterdir()] == ["NOTES.md"]


def test_init_cli_without_uv_reports_and_leaves_no_directory(tmp_path, without):
    without("uv")
    target = tmp_path / "scaffolded"

    result = runner.invoke(app, ["init", str(target), "--yes"])

    assert result.exit_code == 1
    assert "`uv` is not installed" in result.stdout
    assert not target.exists()


def test_git_init_failure_is_its_own_error(tmp_path, without):
    without("git")

    with pytest.raises(GitInitError, match="git-scm.com"):
        init_git_repo(tmp_path)


def test_a_missing_git_warns_but_keeps_the_scaffolded_project(tmp_path, without):
    """git is not what makes the project work."""
    without("git")
    target = tmp_path / "scaffolded"

    result = runner.invoke(app, ["init", str(target), "--yes"])

    assert result.exit_code == 0, result.stdout
    assert "warning:" in result.stdout
    assert "`git` is not installed" in result.stdout
    assert (target / "foro.yaml").is_file()
    assert (target / "uv.lock").is_file()
    assert not (target / ".git").exists()
