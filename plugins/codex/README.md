# foro — Codex plugin

Take a repo from an empty folder to a deployed MCP server on
[foro.sh](https://foro.sh) without leaving Codex. The Codex counterpart of the
[Claude Code plugin](../claude-code/README.md) — same payload, Codex's format.

- **The foro.sh docs MCP server** (`docs.foro.sh`, public, no auth) —
  exposed as the `foro-docs` server so skills can look docs up live instead of
  inlining copy that goes stale.
- **Four skills** covering both ways in (a new project, or one that already
  exists), the deploy itself, and the tool design that decides what a server
  costs to use.

## Install

From a checkout of this repo, the root marketplace at
`.agents/plugins/marketplace.json` offers this plugin for local install. Once
it's in the shared ChatGPT + Codex directory, install it from there instead.

## What's inside

### `foro-docs` MCP server (`.mcp.json`)

A streamable-HTTP server at `https://docs.foro.sh/mcp`, no auth — it's
read-only documentation, so the plugin carries no credential. It exposes:

- `list_docs()` — the available doc slugs and titles
- `read_doc(slug)` — a doc's markdown by slug
- `search_docs(query)` — case-insensitive search across the docs
- `ask_faq(question)` — the docs' structured FAQ entries, ranked by keyword overlap
- `validate_foro_yaml(manifest)` — a manifest against the platform's build-time rules

The skills call these so their guidance tracks the docs rather than hardcoding
it.

### Skills

Codex selects a skill by its description, so these are invoked by asking for
what you want, not by a slash command:

- **create-foro-project** — scaffold a deployable MCP server. Runs
  `uvx foro init`, explains the generated project (pulling the current
  field list from `foro-docs`), states the two constraints that trip up first
  deploys (Python only — though any of uv/PDM/Poetry/pipenv/`requirements.txt`
  ships; secrets in the dashboard, never the repo), and finishes with
  `foro check` + `foro dev`, claiming success only on a real local `/mcp`
  response.
- **add-foro-to-existing-server** — the other way in, for a server that already
  works locally. Converts the transport (a working local server is almost always
  on stdio, which never opens a port and fails the deploy health check 60
  seconds in), records anything foro can't infer via `foro init`, and proves it with `foro dev`
  before anything reaches the cloud.
- **deploy-to-foro** — get it live. `git init` → commit → `gh repo create
  --push`, then the dashboard step (pick repo, add secrets, Deploy — honestly a
  browser step, there's no user deploy API yet). The result is a random,
  immutable `https://<slug>.foro.sh` URL. When a deploy fails, it points at the
  build-vs-deploy log split and the usual suspects.
- **design-mcp-tools** — shape the tools themselves. A tool's schema is resent
  on every request whether it's called or not, so descriptions, enum size, and
  tool count are a standing cost on every message. Covers the levers in payoff
  order and ends at the dashboard's real numbers rather than a feeling.

All four `SKILL.md` files are byte-identical to the Claude Code plugin's, and CI
fails if they drift. `plugins/claude-code/skills/` is the canonical copy.

## Requirements

- The [`foro` CLI](https://pypi.org/project/foro/) via `uv` — the skills run
  `uvx foro ...`, so no separate install is needed beyond `uv`.
- [`gh`](https://cli.github.com/) for the GitHub push step in `deploy-to-foro`.

## Assets

`assets/logo.png` and `assets/icon.png` are rendered from `assets/foro-mark.svg`
(the foro.sh mark) for the directory listing:

```sh
npx -y sharp-cli --input assets/foro-mark.svg --output assets/logo.png resize 512 512
npx -y sharp-cli --input assets/foro-mark.svg --output assets/icon.png  resize 128 128
```

`interface.screenshots` is deliberately absent — the portal requires screenshots
at submission, and there are no real ones yet. Take them from a live deploy
rather than mocking them up.

## Scope

Skills only. No hooks — Codex supports `SessionStart` and friends, but
a hook that fires every session to look for a foro project is the kind of thing
that gets disabled and then rots; the skill descriptions are enough for the
model to reach for them. No agents, no LSP config.
