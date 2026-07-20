from __future__ import annotations

from typer.testing import CliRunner

from foro._manifest import parse_and_validate
from foro.check import run_check
from foro.cli import app
from foro.init import (
    ManifestFields,
    detect_entrypoint_candidates,
    detect_existing_dependency_manager,
    existing_manifest_diff,
    manifest_yaml,
    scaffold_new,
    write_manifest,
)

runner = CliRunner()


# --- detect_entrypoint_candidates ---------------------------------------


def test_detect_entrypoint_finds_fastmcp_server(tmp_path):
    (tmp_path / "server.py").write_text('from fastmcp import FastMCP\nmcp = FastMCP("x")\n')

    assert detect_entrypoint_candidates(tmp_path) == ["server.py"]


def test_detect_entrypoint_ignores_non_fastmcp_files(tmp_path):
    (tmp_path / "server.py").write_text("print('not an mcp server')\n")

    assert detect_entrypoint_candidates(tmp_path) == []


def test_detect_entrypoint_finds_multiple_candidates(tmp_path):
    (tmp_path / "server.py").write_text('FastMCP("a")\n')
    (tmp_path / "main.py").write_text('FastMCP("b")\n')

    assert detect_entrypoint_candidates(tmp_path) == ["server.py", "main.py"]


def test_detect_entrypoint_checks_nested_candidate(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "server.py").write_text('FastMCP("x")\n')

    assert detect_entrypoint_candidates(tmp_path) == ["src/server.py"]


# --- detect_existing_dependency_manager ---------------------------------


def test_detect_dependency_manager_from_uv_lock(tmp_path):
    (tmp_path / "uv.lock").write_text("")

    assert detect_existing_dependency_manager(tmp_path) == "uv"


def test_detect_dependency_manager_none_when_nothing_present(tmp_path):
    assert detect_existing_dependency_manager(tmp_path) is None


# --- manifest_yaml / write_manifest / existing_manifest_diff ------------


def test_manifest_yaml_omits_defaults():
    fields = ManifestFields(name="x", entrypoint="server.py")

    text = manifest_yaml(fields)

    assert text == "name: x\nentrypoint: server.py\n"


def test_manifest_yaml_includes_non_default_fields():
    fields = ManifestFields(
        name="x", entrypoint="server.py", python_version="3.11", port=9000, dependency_manager="poetry"
    )

    text = manifest_yaml(fields)

    assert "python_version: '3.11'" in text or "python_version: \"3.11\"" in text
    assert "port: 9000" in text
    assert "dependency_manager: poetry" in text


def test_existing_manifest_diff_none_when_no_file(tmp_path):
    fields = ManifestFields(name="x", entrypoint="server.py")

    assert existing_manifest_diff(tmp_path, fields) is None


def test_existing_manifest_diff_empty_when_identical(tmp_path):
    fields = ManifestFields(name="x", entrypoint="server.py")
    write_manifest(tmp_path, fields)

    assert existing_manifest_diff(tmp_path, fields) == ""


def test_existing_manifest_diff_shows_changes(tmp_path):
    write_manifest(tmp_path, ManifestFields(name="old", entrypoint="server.py"))

    diff = existing_manifest_diff(tmp_path, ManifestFields(name="new", entrypoint="server.py"))

    assert "-name: old" in diff
    assert "+name: new" in diff


# --- scaffold_new ---------------------------------------------------------


def test_scaffold_new_writes_a_project_that_passes_check(tmp_path):
    target = tmp_path / "scaffolded"
    fields = ManifestFields(name="scaffolded", entrypoint="server.py", python_version="3.12", port=8000)

    scaffold_new(target, fields, git_init=False)

    assert (target / "server.py").exists()
    assert (target / "app.py").exists()
    assert (target / "tools" / "__init__.py").exists()
    assert (target / "tools" / "add.py").exists()
    assert (target / "tests" / "test_tools.py").exists()
    assert (target / "pyproject.toml").exists()
    assert (target / "foro.yaml").exists()
    assert (target / "uv.lock").exists()
    assert (target / "README.md").exists()
    assert (target / ".gitignore").exists()
    assert (target / ".env.example").exists()
    assert not (target / ".git").exists()

    manifest = parse_and_validate(target, ".")
    assert manifest.name == "scaffolded"

    result = run_check(target)
    assert result.ok, result.message


def test_scaffold_new_git_init(tmp_path):
    target = tmp_path / "with-git"
    fields = ManifestFields(name="with-git", entrypoint="server.py")

    scaffold_new(target, fields, git_init=True)

    assert (target / ".git").is_dir()


def test_scaffold_new_respects_custom_entrypoint(tmp_path):
    # app.py/tools/ are fixed structural filenames, independent of the
    # entrypoint's own name - "custom entrypoint" only ever means the file
    # foro.yaml points at as the deploy entrypoint.
    target = tmp_path / "custom-entry"
    fields = ManifestFields(name="custom-entry", entrypoint="run.py")

    scaffold_new(target, fields, git_init=False)

    assert (target / "run.py").exists()
    assert not (target / "server.py").exists()
    assert (target / "app.py").exists()


# --- CLI: from-scratch mode ----------------------------------------------


def test_cli_init_from_scratch(tmp_path):
    target = tmp_path / "cli-scratch"

    result = runner.invoke(
        app,
        ["init", str(target)],
        input="\n\n\nn\n",  # accept name/python_version/port defaults, decline git init
    )

    assert result.exit_code == 0, result.stdout
    assert (target / "foro.yaml").exists()
    manifest = parse_and_validate(target, ".")
    assert manifest.name == "cli-scratch"
    assert manifest.entrypoint == "server.py"
    assert not (target / ".git").exists()


def test_cli_init_from_scratch_refuses_nonempty_target(tmp_path):
    target = tmp_path / "occupied"
    target.mkdir()
    (target / "existing-file.txt").write_text("hi")

    result = runner.invoke(app, ["init", str(target)])

    assert result.exit_code == 1
    assert "not empty" in result.stdout


# --- CLI: existing-repo mode -----------------------------------------------


def test_cli_init_existing_repo_writes_only_manifest(tmp_path, monkeypatch):
    (tmp_path / "server.py").write_text('from fastmcp import FastMCP\nmcp = FastMCP("x")\n')
    (tmp_path / "uv.lock").write_text("")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["init"], input="\n\n\n\n\n")  # accept all detected defaults

    assert result.exit_code == 0, result.stdout
    manifest = parse_and_validate(tmp_path, ".")
    assert manifest.entrypoint == "server.py"
    # detected uv.lock -> no explicit override needed
    assert manifest.dependency_manager is None
    assert not (tmp_path / "pyproject.toml").exists()


def test_cli_init_existing_repo_rejects_non_py_entrypoint_and_reprompts(tmp_path, monkeypatch):
    (tmp_path / "server.py").write_text('from fastmcp import FastMCP\nmcp = FastMCP("x")\n')
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        ["init"],
        # a bad entrypoint answer (a port number, not a path), then a valid
        # one, then the rest as defaults - regression test for a real
        # report: an unvalidated Entrypoint prompt accepted "8000" verbatim
        # and wrote generated server code to a file literally named "8000".
        input="8000\nserver.py\n\n\n\n\n",
    )

    assert result.exit_code == 0, result.stdout
    manifest = parse_and_validate(tmp_path, ".")
    assert manifest.entrypoint == "server.py"
    assert not (tmp_path / "8000").exists()
    assert "must be a relative .py path" in result.stdout


def test_cli_init_existing_repo_declines_overwrite(tmp_path, monkeypatch):
    write_manifest(tmp_path, ManifestFields(name="original", entrypoint="server.py"))
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["init"], input="alt.py\n\ndifferent\n\n\nn\n")

    assert result.exit_code == 1
    manifest = parse_and_validate(tmp_path, ".")
    assert manifest.name == "original"
