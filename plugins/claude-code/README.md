# foro — Claude Code plugin

Take a repo from an empty folder to a deployed MCP server on
[foro.sh](https://foro.sh) without leaving your agent. The plugin bundles two
things that already exist but that agents can't reach on their own:

- **The foro.sh docs MCP server** (`docs.foro.sh`, public, no auth) —
  exposed as the `foro-docs` server so skills can look docs up live instead of
  inlining copy that goes stale.
- **Six skills** covering both ways in (a new project, or one that already
  exists), building on an existing HTTP API, the deploy itself, and the tool
  design that decides what a server costs to use.

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
- `validate_project_config(files)` — a `pyproject.toml` or `package.json` checked the way a deploy would
- `scaffold_project_config(name, …)` — the smallest `pyproject.toml` / `package.json` foro can deploy
- `client_config(slug, client)` — ready-to-paste client config for a deployed server

Once the plugin is enabled these appear in `/context`. The skills call them so
their guidance stays current with the docs rather than hardcoding it.

### Skills

Skills are namespaced by the plugin name:

- **`/foro:create-foro-project`** — scaffold a deployable MCP server. Runs
  `uvx foro init`, explains the generated project (pulling the current
  field list from `foro-docs`), states the two constraints that trip up first
  deploys (Python or Node, though `foro init` itself only scaffolds Python;
  secrets in the dashboard, never the repo), and finishes with
  `foro check` + `foro dev`, claiming success only on a real local `/mcp`
  response.
- **`/foro:add-foro-to-existing-server`** — the other way in, for a server that
  already works locally. Converts the transport (a working local server is
  almost always on stdio, which never opens a port and fails the deploy health
  check 60 seconds in), records anything foro can't infer via `foro init`, and proves it with
  `foro dev` before anything reaches the cloud.
- **`/foro:deploy-to-foro`** — get it live. `foro auth login` (a device flow
  the skill hands to the user rather than faking), then `foro deploy`, which
  uploads the working tree or builds a linked repo's branch and streams the
  build. It names the secrets to set in the dashboard, and claims success only
  once `foro verify` lists the tools at the random, immutable
  `https://<slug>.foro.sh` URL.
- **`/foro:debug-a-foro-deploy`** — when a deploy fails or the URL doesn't
  answer. Reads the right log first (`foro logs --build` vs `--deploy`),
  walks the usual suspects, and reproduces with `foro dev` instead of
  redeploying to test a guess.
- **`/foro:design-mcp-tools`** — shape the tools themselves. A tool's schema is
  resent on every request whether it's called or not, so descriptions, enum
  size, and tool count are a standing cost on every message. Covers the levers
  in payoff order and ends at the dashboard's real numbers rather than a
  feeling.
- **`/foro:wrap-an-http-api`** — build tools on an existing API from its real
  contract. A client written from memory deploys green and 404s on every call,
  so it finds the API's own spec first (`/openapi.json` and friends), falls
  back to pasted docs, then to probing the live API, and queries specs with
  `jq` from `.foro/specs/` instead of reading them whole.

## Requirements

- The [`foro` CLI](https://pypi.org/project/foro/) via `uv` — the skills run
  `uvx foro ...`, so no separate install is needed beyond `uv`.
- A [foro.sh](https://foro.sh) account for `deploy-to-foro` and `debug-a-foro-deploy`.

## Scope

Skills only. No hooks, no agents, no LSP config — nothing here needs to
intercept tool calls or run in the background.
