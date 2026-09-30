import hashlib
from pathlib import Path

import anyio
import pytest
from fastmcp import Client, FastMCP
from mcp.shared.exceptions import MCPError
from mcp_types import Request, RequestParams
from pydantic import TypeAdapter

import foro


def _skill(root: Path, name: str, frontmatter: str, files: dict[str, str] | None = None) -> None:
    skill = root / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(f"---\n{frontmatter}---\n\n# {name}\n")
    for path, text in (files or {}).items():
        (skill / path).parent.mkdir(parents=True, exist_ok=True)
        (skill / path).write_text(text)


def _server(root: Path) -> FastMCP:
    server = FastMCP("t")
    foro.skills(server, root)
    return server


class _Params(RequestParams, extra="allow"):
    pass


def _request(server: FastMCP, method: str, params: dict) -> dict:
    async def go():
        async with Client(server) as client:
            return await client.session.send_request(
                Request(method=method, params=_Params(**params)), TypeAdapter(dict)
            )

    return anyio.run(go)


def test_list_serves_every_file_with_a_digest_the_bytes_match(tmp_path):
    _skill(
        tmp_path,
        "weekly-review",
        "name: weekly-review\ndescription: Review the week.\nmetadata:\n  version: 1\n",
        {"references/checklist.md": "# Checklist\n"},
    )
    server = _server(tmp_path)

    [entry] = _request(server, "skills/list", {})["skills"]

    assert entry["uri"] == "skill://weekly-review/SKILL.md"
    # Typed, not stringified: a host compares these against its own YAML parse.
    assert entry["frontmatter"]["metadata"] == {"version": 1}
    assert [f["uri"] for f in entry["resources"]] == [
        "skill://weekly-review/SKILL.md",
        "skill://weekly-review/references/checklist.md",
    ]
    for f in entry["resources"]:
        raw = (tmp_path / f["uri"].removeprefix("skill://")).read_bytes()
        assert f["digest"] == "sha256:" + hashlib.sha256(raw).hexdigest()
        assert f["size"] == len(raw)


def test_get_returns_the_listed_entry_and_rejects_an_unknown_uri(tmp_path):
    _skill(tmp_path, "a", "name: a\ndescription: A.\n")
    server = _server(tmp_path)

    got = _request(server, "skills/get", {"uri": "skill://a/SKILL.md"})
    assert got["skill"] == _request(server, "skills/list", {})["skills"][0]

    with pytest.raises(MCPError) as err:
        _request(server, "skills/get", {"uri": "skill://nope/SKILL.md"})
    assert err.value.error.code == -32602


def test_the_extension_is_declared(tmp_path):
    _skill(tmp_path, "a", "name: a\ndescription: A.\n")
    server = _server(tmp_path)

    async def go():
        async with Client(server) as client:
            return client.session.discover_result or client.session.initialize_result

    capabilities = anyio.run(go).capabilities
    assert "io.modelcontextprotocol/skills" in (capabilities.extensions or {})


def test_a_name_that_is_not_its_directory_fails_at_startup(tmp_path):
    _skill(tmp_path, "a", "name: b\ndescription: A.\n")

    with pytest.raises(ValueError, match="must match its directory"):
        _server(tmp_path)


def test_no_skills_fails_at_startup(tmp_path):
    with pytest.raises(FileNotFoundError):
        _server(tmp_path)
