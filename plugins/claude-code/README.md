# foro — Claude Code plugin

Take a repo from an empty folder to a deployed MCP server on
[foro.sh](https://foro.sh) without leaving your agent. The plugin bundles two
things that already exist but that agents can't reach on their own:

- **The foro.sh docs MCP server** (`docs-mcp.foro.sh`, public, no auth) —
  exposed as the `foro-docs` server so skills can look docs up live instead of
  inlining copy that goes stale.
- **Two skills** that encode the `foro init` → `foro.yaml` → push → deploy path.

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
  `uvx foro init`, explains the generated `foro.yaml` (pulling the current
  field list from `foro-docs`), states the two constraints that trip up first
  deploys (Python + `uv` only; secrets in the dashboard, never the repo), and
  finishes with `foro check` + `foro dev`, claiming success only on a real
  local `/mcp` response.
- **`/foro:deploy-to-foro`** — get it live. `git init` → commit →
  `gh repo create --push`, then the dashboard step (pick repo, add secrets,
  Deploy — honestly a browser step, there's no user deploy API yet). The result
  is a random, immutable `https://<slug>.foro.sh` URL. When a deploy fails, it
  points at the build-vs-deploy log split and the usual suspects.

## Requirements

- The [`foro` CLI](https://pypi.org/project/foro/) via `uv` — the skills run
  `uvx foro ...`, so no separate install is needed beyond `uv`.
- [`gh`](https://cli.github.com/) for the GitHub push step in `deploy-to-foro`.

## Scope

Two skills, by design. No hooks, no agents, no LSP config — nothing here needs
to intercept tool calls or run in the background. A `debug-foro-deploy` skill is
a plausible third, to be added once we've seen which failures people actually
hit. No TypeScript-project skill until the TS SDK supports deploys.
