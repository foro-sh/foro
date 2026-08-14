# foro (Python)

[![PyPI](https://img.shields.io/pypi/v/foro?color=3775A9)](https://pypi.org/project/foro/)
[![Python](https://img.shields.io/pypi/pyversions/foro)](https://pypi.org/project/foro/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](../../LICENSE)

The Python SDK and CLI for [foro.sh](https://foro.sh) — the fastest path from
"I want to build an MCP server" to a deployed `https://<slug>.foro.sh` URL.

- [Quickstart](#quickstart)
- [CLI](#cli)
- [Runtime](#runtime)
- [Project config](#project-config)
- [Example](#example)
- [Develop this package](#develop-this-package)

## Quickstart

```bash
uvx foro init my-server && cd my-server
uvx foro dev
```

`foro init` scaffolds a working [FastMCP](https://gofastmcp.com) server;
`foro dev` runs it exactly as foro.sh will and confirms it would pass the
platform's health check. Once it looks good:

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
| `foro init [name]` | Scaffold a new project, or record an existing one's foro settings in its `pyproject.toml` (run with no argument). `--yes` takes every default without prompting, for CI and coding agents |
| `foro check [path]` | Validate a repo against foro.sh's deploy contract before you push |
| `foro dev [path]` | Run the server locally exactly as foro.sh will, and confirm it would pass the health check |
| `foro verify <url>` | Prove a deployed server actually serves MCP, by opening a session and listing its tools |
| `foro auth <login\|status\|logout\|token>` | Sign in to foro.sh, so the CLI can act on your behalf |

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

## Signing in

`init`, `check` and `dev` are entirely local and need no account. `foro auth`
is for everything that talks to foro.sh:

```console
$ foro auth login
! First copy your one-time code: 7A2F-K9QP
Press Enter to open foro.sh in your browser...
- Waiting for authorization... 6s
✓ Logged in as danielsteman (workspace: acme)
```

A browser approves the code, the CLI polls until you do — the same device flow
`gh auth login` uses, so it works over SSH where a loopback redirect wouldn't.

- **The token is workspace-scoped**, picked when you approve it. Access to a
  second workspace means logging in again for a second token; there is no
  workspace-switch command.
- **`foro auth status`** validates against the API rather than reporting that a
  file exists, so a revoked token shows as broken. It exits 1 when you aren't
  authenticated, which is what a script should branch on.
- **`foro auth logout`** revokes the token server-side *and* deletes it here. If
  revocation fails it still deletes locally and tells you to finish the job on
  `/account`.
- **`foro auth token`** prints the raw token and nothing else, for
  `curl -H "Authorization: Bearer $(foro auth token)"`.

Credentials live in `~/.config/foro/hosts.yml` (`$XDG_CONFIG_HOME` is honoured;
`%APPDATA%\foro` on Windows) at mode `0600`, keyed by host. Two environment
variables override it:

| Variable | Effect |
| --- | --- |
| `FORO_TOKEN` | Use this token instead of the stored one, and never write it to disk — the `GH_TOKEN` convention. `foro auth status` says when it's in play |
| `FORO_HOST` | Point the CLI at another instance (`localhost:3001` for a native dev stack). Defaults to `foro.sh` |

For CI, skip the browser entirely:

```console
$ echo "$FORO_TOKEN" | foro auth login --with-token
```

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
    foro.run(mcp)  # streamable HTTP, host 0.0.0.0, port $PORT - identical locally and deployed
```

| Function | What it does |
| --- | --- |
| `foro.run(server, *, port=None)` | The one correct way to start a server for foro.sh. Accepts any FastMCP-shaped server (standalone `fastmcp.FastMCP`, `mcp.server.fastmcp.FastMCP`, or a low-level `Server`) — it's duck-typed, not tied to a specific class. |
| `foro.secret(name)` | Read a required secret from the environment, raising a dashboard-actionable error if it's missing. Set secrets in your project's Secrets tab on the dashboard; they arrive as env vars at deploy time. |

Bare `foro` (what a deployed container installs — no `[cli]` extra) stays
dependency-free, so a deployed container never pulls in CLI tooling it
doesn't use.

## Project config

There is no foro-specific manifest. A repo's `pyproject.toml` (Python) or
`package.json` (Node) already names the project and points at the file that
starts it, and that is what foro.sh reads:

| What foro needs | Python | Node |
| --- | --- | --- |
| display name | `[project].name` | `name` |
| runtime | a `pyproject.toml` is here | a `package.json` is here |
| interpreter version | `requires-python`, resolved to the newest supported version it allows | `engines.node`, same |
| entry file | `server.py`, `main.py`, `src/server.py` or `app.py` | `main`, then `bin`, then `index.js` |
| dependency manager | the lockfile (uv, PDM, Poetry, pipenv, `requirements.txt`) | the lockfile (npm, pnpm, yarn) |

The rest is optional, and only for what those files can't say:

```toml
# pyproject.toml - every key optional, most projects have no such table
[tool.foro]
entrypoint = "cmd/serve.py"   # only when it isn't one of the names above
runtime_version = "3.13"      # only to pin against what requires-python allows
port = 9000                   # only when your server can't listen on $PORT
dependency_manager = "poetry" # only when a repo is genuinely ambiguous
```

```json
// package.json - the same keys, under "foro"
{ "foro": { "port": 9000 } }
```

At runtime the container gets `PORT` and every project secret as its own env
var. Public traffic arrives at
`https://<slug>.foro.sh`, so your server must listen on `0.0.0.0:$PORT` —
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
