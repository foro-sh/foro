# foro — Claude Code plugin

Take a repo from an empty folder to a deployed MCP server on
[foro.sh](https://foro.sh) without leaving your agent. The plugin bundles two
things that already exist but that agents can't reach on their own:

- **The foro.sh docs MCP server** (`docs-mcp.foro.sh`, public, no auth) —
  exposed as the `foro-docs` server so skills can look docs up live instead of
  inlining copy that goes stale.
- **Five skills** covering both ways in (a new project, or one that already
  exists), the deploy itself, what to do when a deploy fails, and the tool
  design that decides what a server costs to use. Together they cover the whole
  arc: a prompt describing a server, to a live URL.

## Install

```
/plugin marketplace add foro-sh/foro
/plugin install foro
```

Or test it locally from a checkout of the SDK repo:

```
claude --plugin-dir ./plugins/claude-code
```

## What's inside

### `foro-docs` MCP server (`.mcp.json`)

Points at the public docs MCP at `https://docs-mcp.foro.sh/mcp` (streamable
HTTP, no auth). It exposes:

- `list_docs()` — the available doc slugs and titles
- `read_doc(slug)` — a doc's markdown by slug
- `search_docs(query)` — case-insensitive search across the docs

Once the plugin is enabled these appear in `/context`. The skills call them so
their guidance stays current with the docs rather than hardcoding it.

### Skills

Skills are namespaced by the plugin name:

- **`/foro:create-foro-project`** — scaffold a deployable MCP server. Runs
  `uvx foro init --yes`, explains the generated `foro.yaml` (pulling the current
  field list from `foro-docs`), states the two constraints that trip up first
  deploys (Python only — though any of uv/PDM/Poetry/pipenv/`requirements.txt`
  ships; secrets in the dashboard, never the repo), replaces the scaffolded
  example tool with the ones the user actually asked for, and finishes with
  `foro check` + `foro dev`, claiming success only on a real local `/mcp`
  response.
- **`/foro:add-foro-to-existing-server`** — the other way in, for a server that
  already works locally. Converts the transport (a working local server is
  almost always on stdio, which never opens a port and fails the deploy health
  check 60 seconds in), adds `foro.yaml` via `foro init`, and proves it with
  `foro dev` before anything reaches the cloud.
- **`/foro:deploy-to-foro`** — get it live with `uvx foro deploy`: no repo, no
  push, no dashboard round trip. It covers the one step an agent can't take —
  the one-time `foro auth login`, where a human has to approve a code in a
  browser — then the upload-vs-branch fork, and verifying the deployed `/mcp`
  actually answers before calling it done. The URL is a random, immutable
  `https://<slug>.foro.sh`.
- **`/foro:debug-a-foro-deploy`** — for when that fails. Which of the two log
  streams answers which question (`foro logs --build` for dependency and image
  failures, `--deploy` for entrypoint, binding and health checks), the usual
  suspects in frequency order, and reproducing locally with `foro dev` instead
  of redeploying to test a hypothesis.
- **`/foro:design-mcp-tools`** — shape the tools themselves. A tool's schema is
  resent on every request whether it's called or not, so descriptions, enum
  size, and tool count are a standing cost on every message. Covers the levers
  in payoff order and ends at the dashboard's real numbers rather than a
  feeling.

## Requirements

- The [`foro` CLI](https://pypi.org/project/foro/) via `uv` — the skills run
  `uvx foro ...`, so no separate install is needed beyond `uv`.
- A foro.sh account. `deploy-to-foro` starts with `foro auth login`, which needs
  a browser once per machine.

## Scope

Skills only. No hooks, no agents, no LSP config — nothing here needs to
intercept tool calls or run in the background.

Deliberately absent: a TypeScript-project skill, until the SDK's `foro.bridge()`
lands and makes non-Python servers deployable — at which point
`create-foro-project`'s "Node doesn't ship" line needs revisiting too. Also no
separate `foro auth` skill: signing in is six lines inside `deploy-to-foro`, and
a skill that only ever fires as a sub-step of another never gets selected on its
own.
