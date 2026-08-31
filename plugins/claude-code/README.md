# foro — Claude Code plugin

Take a repo from an empty folder to a deployed MCP server on
[foro.sh](https://foro.sh) without leaving your agent. The plugin bundles two
things that already exist but that agents can't reach on their own:

- **The foro.sh docs MCP server** (`docs.foro.sh`, public, no auth) —
  exposed as the `foro-docs` server so skills can look docs up live instead of
  inlining copy that goes stale.
- **Four skills** covering both ways in (a new project, or one that already
  exists), the deploy itself, and the tool design that decides what a server
  costs to use.

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

Points at the public docs MCP at `https://docs.foro.sh/mcp` (streamable HTTP,
no auth — it's read-only documentation, so the plugin carries no credential).
It exposes:

- `list_docs()` — the available doc slugs and titles
- `read_doc(slug)` — a doc's markdown by slug
- `search_docs(query)` — case-insensitive search across the docs
- `ask_faq(question)` — the docs' structured FAQ entries, ranked by keyword overlap
- `validate_foro_yaml(manifest)` — a manifest against the platform's build-time rules

Once the plugin is enabled these appear in `/context`. The skills call them so
their guidance stays current with the docs rather than hardcoding it.

### Skills

Skills are namespaced by the plugin name:

- **`/foro:create-foro-project`** — scaffold a deployable MCP server. Runs
  `uvx foro init`, explains the generated project (pulling the current
  field list from `foro-docs`), states the two constraints that trip up first
  deploys (Python only — though any of uv/PDM/Poetry/pipenv/`requirements.txt`
  ships; secrets in the dashboard, never the repo), and finishes with
  `foro check` + `foro dev`, claiming success only on a real local `/mcp`
  response.
- **`/foro:add-foro-to-existing-server`** — the other way in, for a server that
  already works locally. Converts the transport (a working local server is
  almost always on stdio, which never opens a port and fails the deploy health
  check 60 seconds in), records anything foro can't infer via `foro init`, and proves it with
  `foro dev` before anything reaches the cloud.
- **`/foro:deploy-to-foro`** — get it live. `git init` → commit →
  `gh repo create --push`, then the dashboard step (pick repo, add secrets,
  Deploy — honestly a browser step, there's no user deploy API yet). The result
  is a random, immutable `https://<slug>.foro.sh` URL. When a deploy fails, it
  points at the build-vs-deploy log split and the usual suspects.
- **`/foro:design-mcp-tools`** — shape the tools themselves. A tool's schema is
  resent on every request whether it's called or not, so descriptions, enum
  size, and tool count are a standing cost on every message. Covers the levers
  in payoff order and ends at the dashboard's real numbers rather than a
  feeling.

## Requirements

- The [`foro` CLI](https://pypi.org/project/foro/) via `uv` — the skills run
  `uvx foro ...`, so no separate install is needed beyond `uv`.
- [`gh`](https://cli.github.com/) for the GitHub push step in `deploy-to-foro`.

## Scope

Skills only. No hooks, no agents, no LSP config — nothing here needs to
intercept tool calls or run in the background.

Deliberately absent: a `debug-foro-deploy` skill. There's no user-facing logs
API, so it could only say which dashboard tab to open, which `deploy-to-foro`
already does. Worth writing once we know the top three real failures. Also no
TypeScript-project skill until the SDK's `foro.bridge()` lands and makes
non-Python servers deployable — at which point `create-foro-project`'s "Node
doesn't ship" line needs revisiting too.
