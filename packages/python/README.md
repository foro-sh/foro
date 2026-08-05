# foro (Python)

[![PyPI](https://img.shields.io/pypi/v/foro?color=3775A9)](https://pypi.org/project/foro/)
[![Python](https://img.shields.io/pypi/pyversions/foro)](https://pypi.org/project/foro/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](../../LICENSE)

The Python SDK and CLI for [foro.sh](https://foro.sh) — the fastest path from
"I want to build an MCP server" to a deployed `https://<slug>.foro.sh` URL.

- [Quickstart](#quickstart)
- [CLI](#cli)
- [Runtime](#runtime)
- [`foro.yaml` reference](#foroyaml-reference)
- [Example](#example)
- [Develop this package](#develop-this-package)

## Quickstart

```bash
uvx foro init my-server && cd my-server
uvx foro dev
```

`foro init` scaffolds a working [FastMCP](https://gofastmcp.com) server plus
a `foro.yaml`; `foro dev` runs it exactly as foro.sh will and confirms it
would pass the platform's health check. Once it looks good:

```bash
git init && git add -A && git commit -m "init" && gh repo create --push
```

Then, on the [foro.sh](https://foro.sh) dashboard: sign in with GitHub, pick
the repo, add any secrets your tools need, and deploy.

## CLI

Install once with `uv tool install foro`, or run ad-hoc with
`uvx foro ...` — no need to add it to your project's own dependencies.

| Command | What it does |
| --- | --- |
| `foro init [name]` | Scaffold a new project, or add `foro.yaml` to an existing one (run with no argument). `--yes` takes every default without prompting, for CI and coding agents |
| `foro check [path]` | Validate a repo against foro.sh's deploy contract before you push |
| `foro dev [path]` | Run the server locally exactly as foro.sh will, and confirm it would pass the health check. `--once` verifies and exits instead of staying up, for CI and coding agents |
| `foro verify <url>` | Prove a deployed server actually serves MCP, by opening a session and listing its tools |

`foro check` mirrors the platform's own validation rule for rule, so a repo
it passes will deploy and one it flags will not — the same reason code,
surfaced locally instead of as a 60-second health-check timeout.

`foro verify` applies `foro dev`'s standard to a deployed server: a URL that
answers HTTP is not the same as one serving MCP, and a green deploy only means
the container passed a TCP probe. It runs the same handshake `foro dev` does —
`initialize`, then `tools/list` — and exits non-zero when that fails, so a
script or a CI step can branch on it.

```console
$ foro verify https://swift-harbor-a3f2.foro.sh
✓ https://swift-harbor-a3f2.foro.sh/mcp is serving MCP
Tools: get_forecast, list_cities
```

The `/mcp` path is appended when you leave it off, so the URL `foro deploy`
printed works as-is.

## Runtime

One import, used from your server's entrypoint:

```python
from fastmcp import FastMCP
import foro

mcp = FastMCP("my-server")

@mcp.tool
def add(a: int, b: int) -> int:
    return a + b

if __name__ == "__main__":
    foro.run(mcp)  # streamable HTTP, host 0.0.0.0, port $MCP_PORT - identical locally and deployed
```

| Function | What it does |
| --- | --- |
| `foro.run(server, *, port=None)` | The one correct way to start a server for foro.sh. Accepts any FastMCP-shaped server (standalone `fastmcp.FastMCP`, `mcp.server.fastmcp.FastMCP`, or a low-level `Server`) — it's duck-typed, not tied to a specific class. |
| `foro.secret(name)` | Read a required secret from the environment, raising a dashboard-actionable error if it's missing. Set secrets in your project's Secrets tab on the dashboard; they arrive as env vars at deploy time. |

Bare `foro` (what a deployed container installs — no `[cli]` extra) stays
dependency-free, so a deployed container never pulls in CLI tooling it
doesn't use.

## `foro.yaml` reference

Every deployable repo carries one, at its root:

```yaml
name: my-server          # required, ^[a-z0-9-]{3,48}$ - display name only, not the URL slug
entrypoint: server.py    # required, relative path, run as `uv run <entrypoint>`
build_path: .            # optional, default "." - dir holding pyproject.toml + uv.lock
python_version: "3.12"   # optional, one of 3.11 / 3.12 / 3.13
port: 8000               # optional, default 8000 - the port your server must listen on
```

At runtime the container gets `MCP_PORT` (matching `port` above) and every
project secret as its own env var. Public traffic arrives at
`https://<slug>.foro.sh`, so your server must listen on `0.0.0.0:$MCP_PORT` —
which is exactly what `foro.run()` does for you.

## Example

[`foro-sh/todo-mcp`](https://github.com/foro-sh/todo-mcp) is a small stateful
todo-list server built the way described above — every new foro.sh workspace
gets a deployed copy of it to poke at before deploying anything of your own.

## Develop this package

```bash
uv sync
uv run pytest
```
