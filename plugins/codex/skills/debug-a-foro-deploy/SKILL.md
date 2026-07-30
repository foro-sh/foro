---
name: debug-a-foro-deploy
description: Work out why a foro.sh deploy failed or why a deployed MCP server isn't answering. Use when `foro deploy` reported failed, the https://<slug>.foro.sh URL returns an error or nothing, the dashboard's Tools tab is empty, a deploy timed out on its health check, or the user asks how to read foro.sh build and deploy logs.
---

# Debug a foro.sh deploy

Deploys fail in a small number of ways, and each one lives in a specific log. The
job is to read the right stream first rather than guessing from the symptom.

## Read the right log

foro.sh keeps two separate streams per deployment, and they answer different
questions:

```bash
uvx foro logs --build     # raw `docker build` stdout/stderr
uvx foro logs --deploy    # the orchestration narrative
```

Both default to the most recent deployment; `--deployment <id>` picks an older
one, and `--json` gives one object per line for piping.

- **`--build`** is dependency and image problems: a stale lockfile, a package
  that won't install, a `python_version` the deps don't support.
- **`--deploy`** is everything around the container: clone, `foro.yaml`
  validation, container start, health check, and the failure reason. A wrong
  `entrypoint`, a server that never opened a port, an unset secret.

For a server that deployed but is misbehaving at runtime:

```bash
uvx foro logs -f          # tail the live container
uvx foro projects show    # status, source, URL, last deploy
```

Runtime log retention is plan-gated (24h on Free, up to 90d on Enterprise), so
an empty history on a quiet or recently deployed server is normal — not a sign
anything is broken. Say that rather than treating it as a symptom.

## Usual suspects, in rough order of frequency

1. **Stale lockfile** — the lockfile no longer matches `pyproject.toml`, so the
   frozen install fails. Shows up in `--build`. Re-lock (`uv lock`,
   `poetry lock`, …), commit if it's a repo project, deploy again.
2. **Wrong `entrypoint` in `foro.yaml`** — it must point at the file that calls
   `foro.run(...)`. Shows up in `--deploy` as a start failure.
3. **Unset secret** — the code calls `foro.secret("NAME")` and `NAME` was never
   added in the dashboard's Secrets tab. The error names the key; add it and
   redeploy.
4. **Server doesn't bind correctly** — it must listen on `0.0.0.0:$MCP_PORT`,
   which `foro.run()` does for you. A hand-rolled `run()` on `127.0.0.1` or a
   fixed port fails the health check in a way that reads like a crash. Shows up
   in `--deploy` as a health-check timeout with a container that started fine.
5. **Still on stdio** — `mcp.run()` with no transport never opens a port at all.
   Same symptom as above, different cause, and the most common one for a server
   that was ported from a local-only setup.

## The change isn't in the build

Before debugging the code, check whether what you're testing was even deployed.
For a project whose `source` is `github`, `foro deploy` builds the repo
**branch** — uncommitted or unpushed work is not in it. `foro projects show`
gives the source; a `git status` and a check for unpushed commits gives the
rest. This looks exactly like "my fix didn't work" and isn't.

## Reproduce locally instead of redeploying

Most of the list above reproduces in seconds:

```bash
uvx foro check    # manifest, entrypoint, lockfile state - static rules
uvx foro dev      # starts the server as the platform does, and probes the port
```

`foro dev` is what catches the binding and transport failures, because it does
the same TCP probe the platform's health check does and then a real MCP
handshake. A server that times out here would have timed out in the cloud a
minute later. Fix it locally, then deploy again.

Don't redeploy to test a hypothesis you can test with `foro dev`.

## When the URL itself is the problem

If the deploy is `live` but `https://<slug>.foro.sh/mcp` doesn't answer:

```bash
curl -sS -X POST https://<slug>.foro.sh/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

- **Nothing / a connection error** → the container isn't serving; `foro logs -f`.
- **An MCP error response** → the server is up and the problem is in the tool
  code, not the deploy. `foro logs -f` while you retry the call.
- **An empty tool list** → the tools never registered. In a scaffolded project
  every tool module has to be imported in `tools/__init__.py`; a file dropped in
  `tools/` without that import is invisible.

## Looking things up

`foro-docs.list_docs()` and `foro-docs.read_doc(...)` have the current
troubleshooting docs. If the docs server isn't reachable, **say so** and work
from this skill's content rather than presenting remembered detail as current.

## Done when

The cause is named, not guessed — with the log line that shows it — and either
fixed and redeployed, or handed back with the specific thing the user needs to
change.
