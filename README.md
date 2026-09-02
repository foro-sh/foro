# foro

Build an MCP server locally, then know it will run the same anywhere.

[![PyPI](https://img.shields.io/pypi/v/foro?label=PyPI&color=3775A9)](https://pypi.org/project/foro/)
[![npm](https://img.shields.io/npm/v/%40foro-sh%2Fforo?label=npm&color=CB3837)](https://www.npmjs.com/package/@foro-sh/foro)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

`foro` is a small CLI and runtime shim for [FastMCP](https://gofastmcp.com)
servers. It scaffolds a project, checks it, runs it under the same conditions a
container will, and proves a running server actually speaks MCP.

```bash
uvx foro init my-server && cd my-server
uvx foro dev
```

```console
✓ would pass foro.sh's health check (port 8000)
Tools: add
Press Ctrl+C to stop.
```

## Why

A server that works under `mcp dev` can still fail in a container: stdio
instead of streamable HTTP, bound to `127.0.0.1` instead of `0.0.0.0`, a
hardcoded port, a secret read with a bare `KeyError`. Every one of those
surfaces as a health check that times out with no useful output.

```python
from fastmcp import FastMCP
import foro

mcp = FastMCP("my-server")

@mcp.tool
def add(a: int, b: int) -> int:
    return a + b

if __name__ == "__main__":
    foro.run(mcp)  # streamable HTTP, 0.0.0.0, $PORT
```

`foro.run()` is duck-typed over any FastMCP-shaped server, and `foro.secret()`
raises an error that says where to set the missing value. The runtime has no
dependencies of its own, so a container installing `foro` doesn't pull in CLI
tooling it never runs.

## CLI

| Command | What it does |
| --- | --- |
| `foro init [name]` | Scaffold a project, or record settings in an existing `pyproject.toml` |
| `foro check [path]` | Validate a repo against the deploy contract |
| `foro dev [path]` | Run the server the way a container will, and report whether it passes |
| `foro verify <url>` | Open a session against a deployed URL and list its tools |
| `foro auth` | `login`, `status`, `logout`, `token` for [foro.sh](https://foro.sh) |

`init`, `check` and `dev` are local and need no account.

There is no foro-specific manifest. Config comes from `pyproject.toml` or
`package.json`, with an optional `[tool.foro]` table for what those files
can't express. See [`packages/python/README.md`](packages/python/README.md)
for the full reference.

## Claude Code plugin

```
/plugin marketplace add foro-sh/foro
/plugin install foro
```

Adds `/foro:create-foro-project`, `/foro:add-foro-to-existing-server`,
`/foro:deploy-to-foro` and `/foro:design-mcp-tools`, plus a docs MCP server.
There's a [Codex counterpart](plugins/codex) with the same skills.

## Deploying

`foro dev` passing means the server satisfies the contract that
[foro.sh](https://foro.sh) builds against: push the repo, pick it in the
dashboard, add secrets, deploy. Nothing here is locked to that platform —
`foro.run()` is a normal streamable-HTTP server on `$PORT`.

## Packages

| Package | Registry | Status |
| --- | --- | --- |
| [`packages/python`](packages/python) | [`foro`](https://pypi.org/project/foro/) | The SDK |
| [`packages/typescript`](packages/typescript) | [`@foro-sh/foro`](https://www.npmjs.com/package/@foro-sh/foro) | Name reserved, not implemented |

## Contributing

Issues and PRs welcome. Commit messages follow
[Conventional Commits](https://www.conventionalcommits.org/) — commitlint
enforces it on PRs, and semantic-release uses it to cut the changelog.

```bash
npm install
cd packages/python && uv sync && uv run pytest
```

## License

[MIT](LICENSE)
