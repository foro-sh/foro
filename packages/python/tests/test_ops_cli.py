"""The commands that mirror foro's MCP tools: right request, right workspace."""

import pytest
from typer.testing import CliRunner

from foro import _api
from foro.cli import app

from test_cli import logged_in  # noqa: F401

runner = CliRunner()

ME = {
    "email": "me@example.com",
    "workspaces": [
        {"id": "11111111-1111-1111-1111-111111111111", "name": "Acme"},
        {"id": "22222222-2222-2222-2222-222222222222", "name": "Side"},
    ],
}


@pytest.fixture
def api(monkeypatch):
    calls = []
    answers = {
        ("GET", "/api/users/me"): ME,
        ("GET", "/api/repos"): [{"owner": "me", "name": "srv", "default_branch": "main"}],
        ("POST", "/api/projects/p/deployments/d1/rollback"): {"id": "d2", "status": "queued"},
        ("GET", "/api/projects/p"): {"slug": "p", "url": "https://p.foro.sh"},
        ("GET", "/api/projects/p/logs?q=%22a%5C%22b%22"): {"lines": [{"line": "hit"}]},
        ("GET", "/api/projects/p/metrics/sessions/a%2Fb"): {"calls": []},
        ("PATCH", "/api/workspaces"): {"id": ME["workspaces"][1]["id"], "name": "Renamed"},
    }

    def request(method, path, *, host, token=None, body=None, timeout=None, workspace=None):
        calls.append((method, path, workspace, body))
        if path.startswith("/api/projects/p/logs?from="):
            return {"lines": [{"line": "windowed"}]}
        return answers[(method, path)]

    monkeypatch.setattr(_api, "request", request)
    return calls


def test_without_a_default_the_server_picks_the_workspace(logged_in, api):
    result = runner.invoke(app, ["repos"])
    assert result.exit_code == 0, result.stdout
    assert api[-1][:3] == ("GET", "/api/repos", None)


def test_the_root_workspace_option_is_sent_as_its_id(logged_in, api):
    result = runner.invoke(app, ["--workspace", "Side", "workspace", "rename", "Renamed"])
    assert result.exit_code == 0, result.stdout
    assert api[-1] == ("PATCH", "/api/workspaces", ME["workspaces"][1]["id"], {"name": "Renamed"})


def test_rollback_starts_from_the_named_deployment(logged_in, api):
    result = runner.invoke(app, ["rollback", "d1", "--project", "p", "--detach"])
    assert result.exit_code == 0, result.stdout
    assert "rolling back p (d2)" in result.stdout
    assert "https://p.foro.sh/mcp" in result.stdout


def test_a_session_id_with_a_slash_stays_one_path_segment(logged_in, api):
    result = runner.invoke(app, ["sessions", "a/b", "--project", "p"])
    assert result.exit_code == 0, result.stdout


def test_contains_is_sent_as_one_escaped_phrase(logged_in, api):
    result = runner.invoke(app, ["logs", "--project", "p", "--contains", 'a"b'])
    assert result.exit_code == 0, result.stdout
    assert result.stdout == "hit\n"


def test_until_takes_a_utc_offset(logged_in, api):
    result = runner.invoke(app, ["logs", "--project", "p", "--until", "2026-10-27T10:00:00Z"])
    assert result.exit_code == 0, result.stdout
    assert "from=2026-10-27T09%3A00%3A00%2B00%3A00&to=2026-10-27T10%3A00%3A00%2B00%3A00" in api[-1][1]


def test_window_filters_are_refused_where_they_would_be_ignored(logged_in, api):
    result = runner.invoke(app, ["logs", "--project", "p", "--follow", "--contains", "x"])
    assert result.exit_code == 1
    assert not api


@pytest.mark.parametrize("auth_mode, bearer", [("token", "mcp-secret"), ("none", None), ("oauth", None)])
def test_inspect_opens_the_inspector_on_the_deployed_url(logged_in, monkeypatch, auth_mode, bearer):

    import foro.cli as cli_module

    answers = {
        "/api/projects/p": {"slug": "p", "url": "https://p.foro.sh", "auth_mode": auth_mode},
        "/api/projects/p/token": {"token": "mcp-secret"},
    }
    asked = []
    monkeypatch.setattr(
        _api, "request", lambda method, path, **kw: asked.append(path) or answers[path]
    )

    class Inspector:
        def wait(self, timeout=None):
            if timeout is None:
                raise KeyboardInterrupt
            return 0

        def terminate(self):
            self.terminated = True

    started = []
    inspector = Inspector()
    monkeypatch.setattr(cli_module, "start_inspector", lambda url, b=None: started.append((url, b)) or inspector)

    result = runner.invoke(app, ["inspect", "--project", "p"])

    assert result.exit_code == 0, result.stdout
    assert started == [("https://p.foro.sh/mcp", bearer)]
    assert ("/api/projects/p/token" in asked) == (auth_mode == "token")
    assert inspector.terminated
    assert "mcp-secret" not in result.stdout
