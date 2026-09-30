# foro — Cursor plugin

Take a repo from an empty folder to a deployed MCP server on
[foro.sh](https://foro.sh) without leaving Cursor. The Cursor counterpart of the
[Claude Code plugin](../claude-code/README.md) — same payload, Cursor's format.

- **The foro.sh docs MCP server** (`docs.foro.sh`, public, no auth) —
  exposed as the `foro-docs` server so skills can look docs up live instead of
  inlining copy that goes stale.
- **Six skills** covering both ways in (a new project, or one that already
  exists), building on an existing HTTP API, the deploy itself, and the tool
  design that decides what a server costs to use.

## Install

From a checkout of this repo, copy the plugin into Cursor's local-plugin
directory and reload:

```sh
mkdir -p ~/.cursor/plugins/local
cp -R plugins/cursor ~/.cursor/plugins/local/foro
```

Then **Developer: Reload Window**, and confirm the skills and `foro-docs` MCP
under **Customize**.

On a Teams or Enterprise plan, the root marketplace at
`.cursor-plugin/marketplace.json` is what Cursor reads when an admin imports
this repo from **Dashboard → Plugins & MCPs → Add Marketplace**. Paste
`https://github.com/foro-sh/foro`. After that, install **foro** from Customize
the same way as any other marketplace plugin.

It is not in the [public Cursor Marketplace](https://cursor.com/marketplace).

## What's inside

### `foro-docs` MCP server (`mcp.json`)

A streamable-HTTP server at `https://docs.foro.sh/mcp`, no auth — it's
read-only documentation, so the plugin carries no credential. It exposes:

- `list_docs()` — the available doc slugs and titles
- `read_doc(slug)` — a doc's markdown by slug
- `search_docs(query)` — case-insensitive search across the docs
- `ask_faq(question)` — the docs' structured FAQ entries, ranked by keyword overlap
- `validate_project_config(files)` — a `pyproject.toml` or `package.json` checked the way a deploy would
- `scaffold_project_config(name, …)` — the smallest `pyproject.toml` / `package.json` foro can deploy
- `client_config(slug, client)` — ready-to-paste client config for a deployed server

The skills call these so their guidance tracks the docs rather than hardcoding
it.

### Skills

Cursor invokes a skill by name with `/skill-name`, or lets the agent pick one
from its description:

- **`/create-foro-project`** — scaffold a deployable MCP server. Runs
  `uvx foro init`, explains the generated project (pulling the current
  field list from `foro-docs`), states the two constraints that trip up first
  deploys (Python or Node, though `foro init` itself only scaffolds Python;
  secrets in the dashboard, never the repo), and finishes with
  `foro check` + `foro dev`, claiming success only on a real local `/mcp`
  response.
- **`/add-foro-to-existing-server`** — the other way in, for a server that already
  works locally. Converts the transport (a working local server is almost always
  on stdio, which never opens a port and fails the deploy health check 60
  seconds in), records anything foro can't infer via `foro init`, and proves it with `foro dev`
  before anything reaches the cloud.
- **`/deploy-to-foro`** — get it live. `foro auth login` (a device flow
  the skill hands to the user rather than faking), then `foro deploy`, which
  uploads the working tree or builds a linked repo's branch and streams the
  build. It names the secrets to set in the dashboard, and claims success only
  once `foro verify` lists the tools at the random, immutable
  `https://<slug>.foro.sh` URL.
- **`/debug-a-foro-deploy`** — when a deploy fails or the URL doesn't
  answer. Reads the right log first (`foro logs --build` vs `--deploy`),
  walks the usual suspects, and reproduces with `foro dev` instead of
  redeploying to test a guess.
- **`/design-mcp-tools`** — shape the tools themselves. A tool's schema is resent
  on every request whether it's called or not, so descriptions, enum size, and
  tool count are a standing cost on every message. Covers the levers in payoff
  order and ends at the dashboard's real numbers rather than a feeling.
- **`/wrap-an-http-api`** — build tools on an existing API from its real contract.
  A client written from memory deploys green and 404s on every call, so it
  finds the API's own spec first (`/openapi.json` and friends), falls back to
  pasted docs, then to probing the live API, and queries specs with `jq` from
  `.foro/specs/` instead of reading them whole.

All `SKILL.md` files are byte-identical to the Claude Code plugin's, and CI
fails if they drift. `plugins/claude-code/skills/` is the canonical copy.

## Requirements

- The [`foro` CLI](https://pypi.org/project/foro/) via `uv` — the skills run
  `uvx foro ...`, so no separate install is needed beyond `uv`.
- A [foro.sh](https://foro.sh) account for `deploy-to-foro` and `debug-a-foro-deploy`.

## Scope

Skills only. No rules, no hooks, no agents, no commands — nothing here needs to
intercept tool calls or run in the background. Cursor supports those, but a
hook that fires every session to look for a foro project is the kind of thing
that gets disabled and then rots; the skill descriptions are enough for the
model to reach for them.
