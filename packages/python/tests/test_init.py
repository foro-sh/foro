from __future__ import annotations

from typer.testing import CliRunner

from foro._manifest import parse_and_validate
from foro.check import run_check
from foro.cli import app
from foro.init import (
    ManifestFields,
    MissingPyprojectError,
    detect_entrypoint_candidates,
    detect_existing_dependency_manager,
    existing_foro_table_diff,
    foro_table,
    scaffold_new,
    write_foro_table,
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


# --- foro_table / write_foro_table / existing_foro_table_diff -----------


def _pyproject(tmp_path, extra=""):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n' + extra)
    return tmp_path


def test_foro_table_is_none_when_inference_covers_every_answer():
    assert foro_table(ManifestFields(name="x", entrypoint="server.py")) is None


def test_foro_table_records_only_what_inference_cannot_reach():
    table = foro_table(
        ManifestFields(
            name="x",
            entrypoint="cmd/serve.py",
            runtime_version="3.11",
            port=9000,
            dependency_manager="poetry",
        )
    )

    assert table == (
        "[tool.foro]\n"
        'entrypoint = "cmd/serve.py"\n'
        'runtime_version = "3.11"\n'
        "port = 9000\n"
        'dependency_manager = "poetry"\n'
    )


def test_write_foro_table_appends_to_the_existing_pyproject(tmp_path):
    _pyproject(tmp_path)

    assert write_foro_table(tmp_path, ManifestFields(name="x", entrypoint="server.py", port=9000))

    text = (tmp_path / "pyproject.toml").read_text()
    assert text.startswith('[project]\nname = "x"\n')
    assert "[tool.foro]\nport = 9000\n" in text


def test_write_foro_table_writes_nothing_when_there_is_nothing_to_say(tmp_path):
    _pyproject(tmp_path)

    assert not write_foro_table(tmp_path, ManifestFields(name="x", entrypoint="server.py"))
    assert "[tool.foro]" not in (tmp_path / "pyproject.toml").read_text()


def test_write_foro_table_replaces_a_table_that_is_already_there(tmp_path):
    _pyproject(tmp_path, "\n[tool.foro]\nport = 9000\n\n[tool.ruff]\nline-length = 100\n")

    write_foro_table(tmp_path, ManifestFields(name="x", entrypoint="server.py", port=9100))

    text = (tmp_path / "pyproject.toml").read_text()
    assert "port = 9100" in text
    assert "port = 9000" not in text
    # The table it sits between is left exactly where it was.
    assert "[tool.ruff]\nline-length = 100\n" in text


def test_write_foro_table_drops_a_table_that_no_longer_says_anything(tmp_path):
    _pyproject(tmp_path, "\n[tool.foro]\nport = 9000\n")

    assert write_foro_table(tmp_path, ManifestFields(name="x", entrypoint="server.py"))
    assert "[tool.foro]" not in (tmp_path / "pyproject.toml").read_text()


def test_write_foro_table_needs_a_pyproject_to_write_into(tmp_path):
    import pytest

    with pytest.raises(MissingPyprojectError):
        write_foro_table(tmp_path, ManifestFields(name="x", entrypoint="cmd/serve.py"))


def test_existing_foro_table_diff_none_when_there_is_no_table(tmp_path):
    _pyproject(tmp_path)

    assert existing_foro_table_diff(tmp_path, ManifestFields(name="x", entrypoint="server.py")) is None


def test_existing_foro_table_diff_shows_changes(tmp_path):
    _pyproject(tmp_path, "\n[tool.foro]\nport = 9000\n")

    diff = existing_foro_table_diff(
        tmp_path, ManifestFields(name="x", entrypoint="server.py", port=9100)
    )

    assert "-port = 9000" in diff
    assert "+port = 9100" in diff


# --- scaffold_new ---------------------------------------------------------


def test_scaffold_new_writes_a_project_that_passes_check(tmp_path):
    target = tmp_path / "scaffolded"
    fields = ManifestFields(name="scaffolded", entrypoint="server.py", runtime_version="3.12", port=8000)

    scaffold_new(target, fields, git_init=False)

    assert (target / "server.py").exists()
    assert (target / "app.py").exists()
    assert (target / "tools" / "__init__.py").exists()
    assert (target / "tools" / "add.py").exists()
    assert (target / "tests" / "test_tools.py").exists()
    assert (target / "pyproject.toml").exists()
    # A scaffold is the shape inference expects, so it says nothing extra.
    assert "[tool.foro]" not in (target / "pyproject.toml").read_text()
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
    # the platform starts.
    target = tmp_path / "custom-entry"
    fields = ManifestFields(name="custom-entry", entrypoint="run.py")

    scaffold_new(target, fields, git_init=False)

    assert (target / "run.py").exists()
    assert not (target / "server.py").exists()
    assert (target / "app.py").exists()

    # The generated wiring test imports the entrypoint by module name, so a
    # renamed entrypoint has to follow through into it - otherwise the test
    # dies on ModuleNotFoundError for a server.py that was never written.
    assert "importlib.import_module('run')" in (target / "tests" / "test_tools.py").read_text()


# --- CLI: from-scratch mode ----------------------------------------------


def test_cli_init_from_scratch(tmp_path):
    target = tmp_path / "cli-scratch"

    result = runner.invoke(
        app,
        ["init", str(target)],
        input="\n\n\nn\n",  # accept name/runtime_version/port defaults, decline git init
    )

    assert result.exit_code == 0, result.stdout
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


def test_cli_init_existing_repo_touches_only_pyproject(tmp_path, monkeypatch):
    (tmp_path / "server.py").write_text('from fastmcp import FastMCP\nmcp = FastMCP("x")\n')
    (tmp_path / "uv.lock").write_text("")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "my-server"\n')
    monkeypatch.chdir(tmp_path)

    # accept all detected defaults, then decline the trailing git-init prompt
    result = runner.invoke(app, ["init"], input="\n\n\n\n\nn\n")

    assert result.exit_code == 0, result.stdout
    manifest = parse_and_validate(tmp_path, ".")
    assert manifest.entrypoint == "server.py"
    # detected uv.lock -> no explicit override needed
    assert manifest.dependency_manager is None
    # Every answer was one inference already produces, so the file it was
    # asked about is the only one touched, and even that is left alone.
    assert (tmp_path / "pyproject.toml").read_text() == '[project]\nname = "my-server"\n'
    assert not (tmp_path / "foro.yaml").exists()
    assert not (tmp_path / ".git").exists()


def test_cli_init_existing_repo_offers_git_init_when_not_already_a_repo(tmp_path, monkeypatch):
    (tmp_path / "server.py").write_text('from fastmcp import FastMCP\nmcp = FastMCP("x")\n')
    (tmp_path / "uv.lock").write_text("")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "my-server"\n')
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["init"], input="\n\n\n\n\ny\n")  # accept defaults, confirm git init

    assert result.exit_code == 0, result.stdout
    assert "Initialize a git repo here?" in result.stdout
    assert (tmp_path / ".git").is_dir()


def test_cli_init_existing_repo_skips_git_prompt_when_already_a_repo(tmp_path, monkeypatch):
    (tmp_path / "server.py").write_text('from fastmcp import FastMCP\nmcp = FastMCP("x")\n')
    (tmp_path / "uv.lock").write_text("")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "my-server"\n')
    (tmp_path / ".git").mkdir()  # pretend it's already a repo - no real `git init` needed for this
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["init"], input="\n\n\n\n\n")  # no 6th answer needed - no prompt to consume it

    assert result.exit_code == 0, result.stdout
    assert "Initialize a git repo here?" not in result.stdout


def test_cli_init_existing_repo_rejects_non_py_entrypoint_and_reprompts(tmp_path, monkeypatch):
    (tmp_path / "server.py").write_text('from fastmcp import FastMCP\nmcp = FastMCP("x")\n')
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "my-server"\n')
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        ["init"],
        # a bad entrypoint answer (a port number, not a path), then a valid
        # one, then the rest as defaults, then decline git init -
        # regression test for a real report: an unvalidated Entrypoint
        # prompt accepted "8000" verbatim and wrote generated server code
        # to a file literally named "8000".
        input="8000\nserver.py\n\n\n\n\nn\n",
    )

    assert result.exit_code == 0, result.stdout
    manifest = parse_and_validate(tmp_path, ".")
    assert manifest.entrypoint == "server.py"
    assert not (tmp_path / "8000").exists()
    assert "must be a relative .py path" in result.stdout


def test_cli_init_existing_repo_declines_overwrite(tmp_path, monkeypatch):
    (tmp_path / "server.py").write_text('from fastmcp import FastMCP\nmcp = FastMCP("x")\n')
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "my-server"\n\n[tool.foro]\nport = 9000\n'
    )
    monkeypatch.chdir(tmp_path)

    # a different port, then defaults, then decline the overwrite
    result = runner.invoke(app, ["init"], input="\n\n\n9100\nn\n")

    assert result.exit_code == 1
    assert "port = 9000" in (tmp_path / "pyproject.toml").read_text()
