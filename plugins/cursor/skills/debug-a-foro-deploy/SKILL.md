---
name: debug-a-foro-deploy
description: Work out why a foro.sh deploy failed or why a deployed MCP server isn't answering. Use when `foro deploy` reported failed, the https://<slug>.foro.sh URL returns an error or nothing, `foro verify` fails, a deploy timed out on its health check, or the user asks how to read foro.sh build and deploy logs.
---

# Debug a foro.sh deploy

Deploys fail in a small number of ways, and each one lives in a specific log.
Read the right stream first rather than guessing from the symptom.

## Read the right log

foro.sh keeps two streams per deployment, and they answer different questions:

```bash
uvx foro logs --build     # raw `docker build` output
uvx foro logs --deploy    # the orchestration narrative
```

Both default to the most recent deployment; `--deployment <id>` picks an older
one, and `--json` gives one object per line.

- **`--build`** is dependency and image problems: a stale lockfile, a package
  that won't install, a runtime version the dependencies don't support.
- **`--deploy`** is everything around the container: config validation,
  container start, health check, and the failure reason. A wrong entrypoint, a
  server that never opened a port, an unset secret.

For a server that deployed but misbehaves at runtime:

```bash
uvx foro logs -f          # tail the live container
uvx foro projects show    # status, source, URL, last deploy
```

Runtime log retention depends on the plan, so an empty history on a quiet or
recently deployed server is normal, not a symptom.

## Usual suspects, in rough order of frequency

1. **Stale lockfile** — the lockfile no longer matches `pyproject.toml` or
   `package.json`: a failed install in `--build`, or an import error in
   `--deploy`. Re-lock (`uv lock`, `npm install`, …) and deploy again.
2. **Wrong entry file** — the file foro starts must be the one that starts the
   server: the one calling `foro.run(...)` in Python, `main` in `package.json`.
   Shows up in `--deploy` as a start failure.
3. **Unset secret** — the code reads `NAME` but it was never added in the
   dashboard's Secrets tab. The error names the key; add it and redeploy.
4. **Server doesn't bind correctly** — it must listen on `0.0.0.0:$PORT`,
   which `foro.run()` does for you. A hand-rolled server on `127.0.0.1` or a
   fixed port shows up in `--deploy` as a health-check timeout on a container
   that started fine.
5. **Still on stdio** — `mcp.run()` with no transport never opens a port. Same
   symptom as above, and the most common cause for a server ported from a
   local-only setup.

## The change isn't in the build

Before debugging the code, check whether what you're testing was deployed. For
a project whose source is `github`, `foro deploy` builds the repo **branch** —
uncommitted or unpushed work is not in it. `foro projects show` gives the
source; `git status` and a check for unpushed commits give the rest. This looks
exactly like "my fix didn't work" and isn't.

## Reproduce locally instead of redeploying

```bash
uvx foro check    # config, entrypoint, lockfile state
uvx foro dev      # starts the server as the platform does, probes the port, lists tools
```

`foro dev` catches the binding and transport failures in seconds instead of a
60-second cloud health-check timeout. It runs Python projects only; for Node,
install with `npm ci` and start `node <main>` with `PORT` set, which is what the
platform does.

Don't redeploy to test a hypothesis you can test locally.

## When the URL itself is the problem

If the deploy is `live` but the server doesn't behave:

```bash
uvx foro verify https://<slug>.foro.sh
```

- **Connection error or timeout** → the container isn't serving; `foro logs -f`.
- **An MCP error** → the server is up and the problem is in the tool code, not
  the deploy. `foro logs -f` while you retry.
- **An empty tool list** → the tools never registered. In a project from `foro
  init`, check that the entrypoint still calls `load_tools()` and that each
  tool function is decorated with `@mcp.tool`.

## Looking things up

`foro-docs.search_docs(...)` and `foro-docs.read_doc(...)` have the current
troubleshooting docs. If the docs server isn't reachable, say so and work from
this skill rather than presenting remembered detail as current.

## Done when

The cause is named with the log line that shows it, and either fixed and
redeployed, or handed back with the specific thing the user needs to change.
