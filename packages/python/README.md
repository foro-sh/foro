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
| `foro dev [path]` | Run the server locally exactly as foro.sh will, and confirm it would pass the health check |
| `foro auth <login\|status\|logout\|token>` | Sign in to foro.sh, so the CLI can act on your behalf |
| `foro deploy [path]` | Deploy this directory and stream the build until it's live |
| `foro logs [path]` | Tail the running server (`-f`), or read a deployment's `--deploy` / `--build` log |
| `foro projects [show]` | List your projects, or show the one this directory is linked to |
| `foro link <slug>` / `foro unlink` | Adopt a project created in the dashboard, or forget the link |
| `foro open` | Open the deployed URL in a browser |

`foro check` mirrors the platform's own validation rule for rule, so a repo
it passes will deploy and one it flags will not — the same reason code,
surfaced locally instead of as a 60-second health-check timeout.

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

## Deploying

```console
$ foro deploy
- packaged 14 files (0.1 MiB)
- created swift-harbor-a3f2
- deploying swift-harbor-a3f2 (a1b2c3d4)
cloning build context
  │ #8 exporting layers
health check passed
✓ live at https://swift-harbor-a3f2.foro.sh
```

`foro check` runs first, so nothing that can't build gets uploaded. The
indented lines are raw `docker build` output, streamed alongside the deploy
narrative because that's usually where a failure's real cause is. `Ctrl+C`
detaches without cancelling the deploy.

**What gets deployed depends on the project's source**, and the CLI won't
guess wrong quietly:

| Situation | What happens |
| --- | --- |
| Unlinked directory | Creates an **upload** project from the working tree, and links this directory to it |
| Linked, `source: upload` | Uploads the working tree again, then deploys |
| Linked, `source: github` | Builds from the repo branch — and warns about uncommitted or unpushed work, which will *not* be in that build |

`--upload` / `--repo` force either path; `--detach` skips the streaming;
`--project <slug>` acts on a project this directory isn't linked to.

The archive is what git would track — `.gitignore` is honoured, and `.git/`,
`.venv/`, `__pycache__/`, `node_modules/`, `dist/` and `.env*` are always
excluded, so a first deploy can't ship a secret or a 400 MB virtualenv.
`foro.yaml` must be at the root of the directory you deploy, which is where
`foro init` puts it.

The link lives in `.foro/project.json` (gitignored), **not** in `foro.yaml` —
the manifest is the shared, committed build contract, while the slug is
platform-generated and workspace-scoped, so baking it into a committed file
would make a fork deploy into someone else's project.

```console
$ foro logs -f                   # tail the running server
$ foro logs --build              # raw docker output from the last deploy
$ foro logs --deploy --json      # the deploy narrative, one JSON object per line
$ foro projects                  # everything in this token's workspace
$ foro open                      # the deployed URL, in a browser
```

Runtime log retention is plan-gated (24h on Free, up to 90d on Enterprise), so
an empty history on a quiet server is normal rather than broken.

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
