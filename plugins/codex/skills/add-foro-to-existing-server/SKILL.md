---
name: add-foro-to-existing-server
description: Make an MCP server that already exists deployable on foro.sh. Use when the user has a working local MCP server (usually stdio, run through a client's config) and wants it reachable at a public URL, mentions porting or migrating an existing server to foro.sh, or runs `foro init` in a repo that already has code. Converts the transport, adds foro.yaml, and proves it with `foro dev`.
---

# Add foro.sh to an existing MCP server

The repo already works — someone runs it locally through their client's config.
The job is not to rewrite it. It is to change how it *serves* and prove that it
still works, then hand off to `deploy-to-foro`.

## The one failure that matters

**A working local server is almost always on stdio, and stdio never opens a
port.** Clients launch these as a subprocess and talk over pipes, so
`mcp.run()` with no arguments is the normal, correct thing to have written —
and it is exactly what fails on foro.sh, where the platform starts the
container and probes a TCP port. Nothing is wrong with the tools; the server
just never listens.

This fails *late* if you let it: the build succeeds, the container starts, and
the deploy dies 60 seconds later on a health check with no obvious cause. Catch
it locally instead. Everything below is arranged around that.

## Steps

### 1. Find how the server currently starts

Read the entrypoint and locate the `run()` call. You are looking for one of:

- `mcp.run()` / `server.run()` with no transport → **stdio, must change**
- `mcp.run(transport="stdio")` → **stdio, must change**
- `mcp.run(transport="http", host=..., port=...)` → already HTTP, but check it
  binds `0.0.0.0` and reads the port from the environment, not a hardcoded one

### 2. Convert it to `foro.run()`

Replace the run call with:

```python
import foro

foro.run(mcp)   # or whatever the FastMCP instance is called
```

`foro.run()` serves streamable HTTP on all interfaces on `$MCP_PORT` —
identical locally and deployed. Do not hand-roll the equivalent: a server that
binds `127.0.0.1`, or a fixed port that disagrees with `foro.yaml`, fails the
health check in a way that reads like a crash.

Add `foro` to the project's dependencies (it is imported at runtime, unlike the
CLI, which `uvx` runs without installing).

**Keep the stdio path if the user still wants it locally.** Guarding the new
call with an env check is fine — just make sure the deployed path is the HTTP
one.

### 3. Add the manifest

```bash
uvx foro init --yes    # no name argument = add foro.yaml to this repo
```

It detects candidate entrypoints and the dependency manager, then fills in the
name, Python version, and port from what it found. `--yes` accepts all of that
without prompting — required here, since prompting a non-interactive run just
aborts it. Detection uses the same signal the platform will use at deploy time,
and the dependency manager is only written to `foro.yaml` when it disagrees
with detection; if it guessed wrong, edit the file afterwards rather than
dropping `--yes`. An existing `foro.yaml` is never overwritten under `--yes` —
init prints the diff and stops, so reconcile it by hand.

Call `foro-docs.read_doc("foro-yaml")` for the current field reference rather
than reciting fields from memory. If the docs server isn't reachable, **say so**
and continue from this skill's content — don't present remembered fields as the
current list.

### 4. Check, then prove it

```bash
uvx foro check
uvx foro dev
```

`foro check` is static: manifest rules, the entrypoint file existing, the
dependency manager resolving, lockfile state. It can only *warn* about the
transport problem. `foro dev` is what actually catches it — it starts the
server the way the platform does and TCP-probes the port, so a server still on
stdio times out here in seconds instead of in the cloud in a minute.

Read the warnings. Two show up often on existing repos:

- **`mcp.server.fastmcp` imported instead of the standalone `fastmcp` package.**
  Servers built against the official MCP SDK hit this. It deploys, but the
  platform's metrics shim won't attach, so the Tools tab stays empty. Switching
  to the standalone `fastmcp` import is usually a one-line change.
- **No lockfile.** The build falls back to an unlocked install: slower, not
  reproducible. Not fatal. A lockfile that is *out of sync* is fatal — that one
  fails `foro check` outright.

### 5. Move secrets out of the repo

An existing server usually reads config from a `.env` file or hardcoded
constants. On foro.sh, secrets are added in the dashboard's Secrets tab and
arrive as environment variables. Read them with `foro.secret("NAME")`, which
raises a dashboard-actionable error when unset. A local `.env` still works for
`foro dev` — it is a local convenience only, and must not be committed.

## Done when

- The entrypoint calls `foro.run(...)`, not a bare `mcp.run()`.
- `uvx foro check` passes and its warnings have been read out loud, not skipped.
- `uvx foro dev` opens the port and lists the server's real tools.
- No secret is read from a committed file.

Next: `deploy-to-foro` gets it live with `foro deploy`. A repo that already has a
GitHub remote can deploy from its branch, but it doesn't have to — `foro deploy`
ships the working tree either way, and the skill covers which one you get.
