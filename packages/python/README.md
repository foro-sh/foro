# Foro Python SDK

The Python SDK and CLI for [foro.sh](https://foro.sh) — the fastest path from
"I want to build an MCP server" to a deployed `https://<slug>.foro.sh` URL.

## Quickstart

```bash
uvx foro init my-server && cd my-server
uvx foro dev
```

`foro init` scaffolds a working FastMCP server plus a `foro.yaml`; `foro dev`
runs it exactly as foro.sh will and confirms it would pass the platform's
health check. Once it looks good:

```bash
git init && git add -A && git commit -m "init" && gh repo create --push
```

Then, on the [foro.sh](https://foro.sh) dashboard: sign in with GitHub, pick
the repo, add any secrets your tools need, and deploy.

## CLI

| Command | What it does |
| --- | --- |
| `foro init [name]` | Scaffold a new project, or add `foro.yaml` to an existing one (run with no argument) |
| `foro check [path]` | Validate a repo against foro.sh's deploy contract before you push |
| `foro dev [path]` | Run the server locally exactly as foro.sh will, and confirm it would pass the health check |

Install once with `uv tool install 'foro[cli]'`, or run ad-hoc with
`uvx foro ...` — no need to add it to your project's own dependencies.

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

- `foro.run(server, *, port=None)` — the one correct way to start a server for
  foro.sh. Accepts any FastMCP-shaped server (standalone `fastmcp.FastMCP`,
  `mcp.server.fastmcp.FastMCP`, or a low-level `Server`) — it's duck-typed,
  not tied to a specific class.
- `foro.secret(name)` — read a required secret from the environment, raising
  a dashboard-actionable error if it's missing. Set secrets in your project's
  Secrets tab on the dashboard; they arrive as env vars at deploy time.

Bare `foro` (what a deployed container installs — no `[cli]` extra) stays
dependency-free, so a deployed container never pulls in CLI tooling it
doesn't use.

## Example

[`foro-sh/todo-mcp`](https://github.com/foro-sh/todo-mcp) is a small stateful
todo-list server built the way described above — every new foro.sh workspace
gets a deployed copy of it to poke at before deploying anything of your own.

## Develop this package

```bash
uv sync
uv run pytest
```
