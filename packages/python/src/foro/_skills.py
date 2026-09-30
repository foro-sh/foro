"""Agent Skills served over MCP (SEP-2640, `io.modelcontextprotocol/skills`).

FastMCP's `SkillsDirectoryProvider` serves the files through `resources/read`
at `skill://<name>/<path>`; the extension below adds the discovery half the
provider predates: the capability, `skills/list` and `skills/get`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

IDENTIFIER = "io.modelcontextprotocol/skills"

_FRONTMATTER = re.compile(r"\A\ufeff?---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)

# Manifests are computed once at startup from the files on disk, so a listing
# stays valid for as long as the process does. Five minutes is the spec's own
# example; nothing here is per-user, hence public.
_CACHE = {"ttlMs": 300_000, "cacheScope": "public"}


def skills(server, path: str | Path = "skills") -> None:
    """Serve every `<path>/<name>/SKILL.md` as an MCP skill.

    Raises at startup rather than serving a skill a host would reject: the
    directory must exist and each skill's frontmatter `name` must match its
    directory, as the spec requires.
    """
    from fastmcp.server.providers.skills import SkillsDirectoryProvider

    root = Path(path)
    if not root.is_dir():
        raise FileNotFoundError(f"foro.skills: no skills directory at {root.resolve()}")

    provider = SkillsDirectoryProvider(roots=root)
    entries = {}
    for skill in provider.providers:
        entry = _entry(skill.skill_info)
        entries[entry["uri"]] = entry
    if not entries:
        raise FileNotFoundError(f"foro.skills: no <name>/SKILL.md under {root.resolve()}")

    server.add_provider(provider)
    server.add_extension(_extension(list(entries.values()), entries))


def _entry(info) -> dict[str, Any]:
    main = info.path / info.main_file
    # Re-parsed rather than taken from `info.frontmatter`, which FastMCP loads
    # with BaseLoader (every value a string). A host compares the entry
    # field-by-field against its own parse of SKILL.md, so types must survive.
    match = _FRONTMATTER.match(main.read_text(encoding="utf-8"))
    frontmatter = yaml.safe_load(match[1]) if match else None
    if not isinstance(frontmatter, dict) or not frontmatter.get("description"):
        raise ValueError(f"foro.skills: {main} needs frontmatter with a name and a description")
    if frontmatter.get("name") != info.name:
        raise ValueError(
            f"foro.skills: {main} is named {frontmatter.get('name')!r}; "
            f"a skill's name must match its directory, {info.name!r}"
        )
    return {
        "uri": f"skill://{info.name}/{info.main_file}",
        "frontmatter": frontmatter,
        "resources": [
            {"uri": f"skill://{info.name}/{f.path}", "digest": f.hash, "size": f.size}
            for f in info.files
        ],
    }


def _extension(listing: list[dict[str, Any]], by_uri: dict[str, dict[str, Any]]):
    from fastmcp.server.extensions import MethodBinding, ServerExtension
    from mcp.shared.exceptions import MCPError
    from mcp_types import INVALID_PARAMS, PaginatedRequestParams, RequestParams

    class GetSkillParams(RequestParams):
        uri: str

    # ponytail: one page, every skill. Fine at a handful of skills; add a
    # cursor when a server ships enough that one response gets heavy.
    async def list_skills(_ctx, _params):
        return {"resultType": "complete", "skills": listing, **_CACHE}

    async def get_skill(_ctx, params):
        entry = by_uri.get(params.uri)
        if entry is None:
            raise MCPError(INVALID_PARAMS, f"Unknown skill: {params.uri}")
        return {"resultType": "complete", "skill": entry, **_CACHE}

    class Skills(ServerExtension):
        identifier = IDENTIFIER

        def methods(self):
            return (
                MethodBinding("skills/list", PaginatedRequestParams, list_skills),
                MethodBinding("skills/get", GetSkillParams, get_skill),
            )

    return Skills()
