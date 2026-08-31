"""The parts of `foro deploy` that are wrong quietly: what goes into the zip,
how the SSE stream ends, which source a directory deploys as, and whether an
API refusal reads as a sentence."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO

import pytest

from foro import _api, _archive, _project_link, deploy
from foro._api import ApiError
from foro._project_link import ProjectLink


def _project(tmp_path, *, git=False):
    (tmp_path / "foro.yaml").write_text("name: my-server\nentrypoint: server.py\n")
    (tmp_path / "server.py").write_text("# mcp server\n")
    if git:
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    return tmp_path


def _names(archive: _archive.Archive) -> set[str]:
    return set(zipfile.ZipFile(BytesIO(archive.content)).namelist())


# --- the zip contract -------------------------------------------------------


def test_manifest_lands_at_the_archive_root(tmp_path):
    # The platform rejects an archive whose foro.yaml is nested, so this is
    # the difference between deploying and a 422.
    archive = _archive.build(_project(tmp_path))

    assert "foro.yaml" in _names(archive)
    assert archive.file_count == 2


def test_a_directory_without_a_manifest_is_refused_before_uploading(tmp_path):
    (tmp_path / "server.py").write_text("# mcp server\n")

    with pytest.raises(_archive.ArchiveError, match="foro init"):
        _archive.build(tmp_path)


def test_junk_is_excluded_even_when_git_tracks_it(tmp_path):
    _project(tmp_path)
    (tmp_path / ".env").write_text("SECRET=shipped-by-accident\n")
    (tmp_path / ".env.example").write_text("SECRET=\n")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "pyvenv.cfg").write_text("home = /usr\n")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "app.pyc").write_bytes(b"\x00")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-Af"], cwd=tmp_path, check=True)

    names = _names(_archive.build(tmp_path))

    assert ".env" not in names
    assert ".env.example" in names  # documentation, not a secret
    assert not any(name.startswith(".venv/") for name in names)
    assert not any("__pycache__" in name for name in names)


def test_gitignored_files_are_left_out(tmp_path):
    _project(tmp_path, git=True)
    (tmp_path / ".gitignore").write_text("big.bin\n")
    (tmp_path / "big.bin").write_bytes(b"0" * 1024)

    assert "big.bin" not in _names(_archive.build(tmp_path))


def test_outside_a_git_repo_the_walk_still_excludes_junk(tmp_path):
    _project(tmp_path)
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("//\n")

    names = _names(_archive.build(tmp_path))

    assert "foro.yaml" in names
    assert not any("node_modules" in name for name in names)


def test_an_oversized_archive_fails_locally_rather_than_as_a_413(tmp_path, monkeypatch):
    _project(tmp_path)
    monkeypatch.setattr(_archive, "MAX_UPLOAD_BYTES", 128)
    # Incompressible, so the zip really does exceed the cap.
    (tmp_path / "blob.bin").write_bytes(bytes(range(256)) * 64)

    with pytest.raises(_archive.ArchiveError, match="upload limit"):
        _archive.build(tmp_path)


# --- the SSE stream ---------------------------------------------------------


class _SseHandler(BaseHTTPRequestHandler):
    body = b""
    status = 200

    def do_GET(self):
        self.send_response(self.status)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *args):
        pass


@pytest.fixture
def sse_server():
    httpd = HTTPServer(("127.0.0.1", 0), _SseHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"127.0.0.1:{httpd.server_port}", _SseHandler
    httpd.shutdown()


def test_the_done_sentinel_ends_the_stream_and_is_not_yielded(sse_server):
    host, handler = sse_server
    handler.body = (
        b'data: {"line": "cloning"}\n\n'
        b":ping\n\n"  # heartbeat, not data
        b'data: {"line": "building"}\n\n'
        b'data: {"done": true}\n\n'
        b'data: {"line": "never reached"}\n\n'
    )

    lines = [entry["line"] for entry in _api.stream_sse("/s", host=host, token="t")]

    assert lines == ["cloning", "building"]


def test_a_stream_cut_short_just_ends(sse_server):
    # A mid-stream disconnect has no sentinel; the iterator must end rather
    # than hang or raise, so the caller falls through to reading the
    # deployment's final status.
    host, handler = sse_server
    handler.body = b'data: {"line": "cloning"}\n\n'

    assert [entry["line"] for entry in _api.stream_sse("/s", host=host, token="t")] == ["cloning"]


def test_a_refused_stream_raises_rather_than_yielding_nothing(sse_server):
    host, handler = sse_server
    handler.status = 409
    handler.body = b'{"error": "Project is not running"}'

    with pytest.raises(ApiError):
        list(_api.stream_sse("/s", host=host, token="t"))


# --- source inference -------------------------------------------------------


class _ApiRecorder:
    """Stands in for the platform: records calls, replies from a script."""

    def __init__(self, project):
        self.project = project
        self.calls = []

    def request(self, method, path, *, host, token=None, body=None, timeout=None):
        self.calls.append((method, path))
        if path.startswith("/api/projects/") and path.endswith("/deploy"):
            return {"id": "dep-1", "status": "building"}
        return self.project

    def post_multipart(self, path, method="POST", **kwargs):
        self.calls.append((method, path))
        return self.project


@pytest.fixture
def recorder(monkeypatch):
    def install(project):
        rec = _ApiRecorder(project)
        monkeypatch.setattr(deploy._api, "request", rec.request)
        monkeypatch.setattr(deploy._api, "post_multipart", rec.post_multipart)
        return rec

    return install


UPLOAD_PROJECT = {"slug": "swift-harbor-a3f2", "source": "upload", "url": "https://x.foro.sh"}
GITHUB_PROJECT = {"slug": "swift-harbor-a3f2", "source": "github", "url": "https://x.foro.sh"}


def test_an_unlinked_directory_creates_an_upload_project_and_links_it(tmp_path, recorder):
    _project(tmp_path)
    rec = recorder(UPLOAD_PROJECT)

    started = deploy.deploy(tmp_path, "foro.sh", "tok")

    assert started.created
    assert ("POST", "/api/projects/upload") in rec.calls
    assert _project_link.load(tmp_path, "foro.sh").slug == "swift-harbor-a3f2"


def test_a_linked_upload_project_replaces_its_archive(tmp_path, recorder):
    _project(tmp_path)
    _project_link.save(tmp_path, ProjectLink(host="foro.sh", slug="swift-harbor-a3f2"))
    rec = recorder(UPLOAD_PROJECT)

    started = deploy.deploy(tmp_path, "foro.sh", "tok")

    assert not started.created
    assert ("PUT", "/api/projects/swift-harbor-a3f2/upload") in rec.calls


def test_a_linked_github_project_never_uploads_the_working_tree(tmp_path, recorder):
    _project(tmp_path)
    _project_link.save(tmp_path, ProjectLink(host="foro.sh", slug="swift-harbor-a3f2"))
    rec = recorder(GITHUB_PROJECT)

    deploy.deploy(tmp_path, "foro.sh", "tok")

    assert not any(path.endswith("/upload") for _, path in rec.calls)
    assert ("POST", "/api/projects/swift-harbor-a3f2/deploy") in rec.calls


def test_forcing_upload_on_a_github_project_is_refused(tmp_path, recorder):
    _project(tmp_path)
    _project_link.save(tmp_path, ProjectLink(host="foro.sh", slug="swift-harbor-a3f2"))
    recorder(GITHUB_PROJECT)

    with pytest.raises(deploy.DeployError, match="no archive to replace"):
        deploy.deploy(tmp_path, "foro.sh", "tok", force_upload=True)


def test_a_link_for_another_host_is_not_reused(tmp_path):
    _project_link.save(tmp_path, ProjectLink(host="localhost:3001", slug="dev-project"))

    assert _project_link.load(tmp_path, "foro.sh") is None
    assert _project_link.load(tmp_path, "localhost:3001").slug == "dev-project"


@pytest.mark.parametrize(
    "content",
    [
        "",  # a write interrupted before anything landed
        "{not json at all",  # hand-edited into nonsense
        '["wrong", "shape"]',  # valid JSON, not an object
        '{"host": "foro.sh"}',  # an object, but no slug to deploy to
    ],
    ids=["empty", "malformed", "not-an-object", "missing-slug"],
)
def test_an_unreadable_link_reads_as_unlinked_rather_than_crashing(tmp_path, content):
    # .foro/project.json is generated, not authored, so a damaged one should
    # send deploy down its create-and-link path - not abort the command with a
    # traceback about JSON the user never wrote.
    _project_link.link_path(tmp_path).parent.mkdir(parents=True)
    _project_link.link_path(tmp_path).write_text(content)

    assert _project_link.load(tmp_path, "foro.sh") is None


def test_a_pre_1980_timestamp_does_not_fail_the_deploy(tmp_path):
    # The zip format can't represent dates before 1980 and zipfile raises on
    # one by default. Vendored fixtures and restored backups carry them, and
    # failing an entire deploy over an mtime nobody reads is the wrong trade.
    _project(tmp_path)
    ancient = tmp_path / "vendored.txt"
    ancient.write_text("from a tarball with a 1970 mtime\n")
    os.utime(ancient, (0, 0))

    archive = _archive.build(tmp_path)

    assert "vendored.txt" in _names(archive)


def test_uncommitted_and_unpushed_work_is_called_out(tmp_path):
    _project(tmp_path, git=True)
    (tmp_path / "server.py").write_text("# changed, not committed\n")

    warning = deploy.local_changes_warning(tmp_path)

    assert "uncommitted changes" in warning
    assert "will not be included" in warning
    # No remote in a fresh `git init`, which is its own problem worth naming.
    assert "no upstream" in warning


def test_no_warning_outside_a_git_repo(tmp_path):
    _project(tmp_path)

    assert deploy.local_changes_warning(tmp_path) is None


# --- error mapping ----------------------------------------------------------


@pytest.mark.parametrize(
    "status,payload,expected",
    [
        (401, {"error": "Unauthorized"}, "foro auth login"),
        (403, {"reason": "seat_read_only"}, "read-only"),
        (403, {"reason": "repo_provider_not_connected"}, "connect a repo provider"),
        (429, {"reason": "global_capacity"}, "at capacity"),
        (429, {"error": "Server limit reached"}, "Server limit reached"),
        (503, {"error": "Uploads are unavailable"}, "Uploads are unavailable"),
        (422, {"error": "foro.yaml must be at the archive root"}, "archive root"),
    ],
)
def test_api_refusals_read_as_sentences(status, payload, expected):
    err = ApiError(status, payload, json.dumps(payload))

    assert expected in _api.explain(err, action="deploy")
