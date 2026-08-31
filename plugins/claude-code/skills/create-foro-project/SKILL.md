---
name: create-foro-project
description: Scaffold a deployable foro.sh MCP server from scratch. Use when the user wants to create, start, or bootstrap a new MCP server to deploy on foro.sh, mentions `foro init`, or asks how to make a repo deployable to foro.sh. Produces a working local server that passes foro.sh's deploy checks; hand off to the deploy-to-foro skill to get it live.
---

# Create a foro.sh project

Take the user from an empty folder to a deployable MCP server that runs
locally *exactly* the way foro.sh will run it. Do not hand-write the server or
its config — the `foro` CLI scaffolds a version that is guaranteed to pass the
platform's deploy contract, and your job is to run it and explain what it
produced.

## State these two constraints first

They are the top two reasons a first deploy fails, so say them before writing
anything:

1. **Python or Node.** For Python, any of `uv`, PDM, Poetry, pipenv, or a
   plain `requirements.txt` works — the platform detects which from the
   lockfile or `pyproject.toml` in the build directory. `uv` is the default and
   what `foro init` scaffolds, so prefer it for a new project, but never tell
   someone their existing Poetry or `requirements.txt` project can't ship. A
   Node server ships too, built with npm, pnpm or yarn; `foro init` only
   scaffolds Python, so for Node write the server and let its `package.json`
   describe it.
2. **Secrets go in the dashboard, never in the repo.** API keys and tokens are
   added in the project's Secrets tab on the foro.sh dashboard and arrive as
   environment variables at deploy time. Never commit a secret, never put one
   in a config file. In code, read them with `foro.secret("NAME")`, which raises
   a dashboard-actionable error when the secret is unset.

## Steps

### 1. Scaffold with `foro init`

Run the CLI (no need to add `foro` to the project's own dependencies; `uvx`
runs it whatever the project itself is managed with):

```bash
uvx foro init <name> --yes
cd <name>
```

`--yes` takes every default (name from the directory, Python 3.12, port 8000,
git init) instead of prompting. You are running this non-interactively, so
without it `foro init` blocks on its first prompt and aborts. Drop the flag
only when the user is running the command themselves and wants to answer.

`foro init` writes a working [FastMCP](https://gofastmcp.com) server plus
`pyproject.toml` + `uv.lock`. Read the generated files and
**explain what they contain** — the entrypoint, the example tool, and how
`foro.run(...)` starts the server — rather than regenerating them by hand.

If the user already has a working MCP server rather than an empty folder, this
is the wrong skill: use `add-foro-to-existing-server`, which handles the
transport conversion that porting actually turns on.

### 2. Explain the project config (look it up, don't hardcode it)

There is no foro-specific manifest. The platform reads `pyproject.toml` — the
project's name, its `requires-python`, and an entry file it finds by name
(`server.py`, `main.py`, `src/server.py`, `app.py`). Anything those can't say
goes in an optional `[tool.foro]` table, and a scaffolded project needs none of
it. What that table accepts changes over time, so pull the current reference
from the docs MCP instead of trusting anything memorised:

- Call `foro-docs.search_docs("project config")` and read what it returns.
  (`foro-docs.list_docs()` lists every available doc slug.)

The one thing to make unmistakable: **the project's `name` is a display name
only — it is NOT the URL.** foro.sh generates a random, immutable slug
(`adjective-noun-4char`) and serves the server at `https://<slug>.foro.sh`.
Don't let the user believe `name` picks their subdomain.

### 3. Validate and run it locally

```bash
uvx foro check    # validates the repo against foro.sh's deploy contract
uvx foro dev      # runs the server locally exactly as the platform will
```

`foro check` mirrors the platform's validation rule-for-rule: a repo it passes
will deploy, one it flags will not — surfaced instantly instead of as a
60-second health-check timeout in the cloud.

### 4. Only claim success on a real `/mcp` response

Do not report the server as working because `foro dev` printed a banner.
Confirm it actually serves MCP: with `foro dev` running, hit the local
streamable-HTTP endpoint (the `/mcp` path it prints) and verify you get a real
MCP response — an `initialize` handshake or a `tools/list` that returns the
scaffolded tool. If it doesn't respond, it isn't done; read the `foro check` /
`foro dev` output for the specific reason and fix that before moving on.

## Done when

- `foro check` passes.
- `foro dev` serves a real MCP response locally on its `/mcp` path.
- The user understands: Python or Node, secrets live in the dashboard, and
  the deployed URL is a generated slug, not the project's `name`.

Next: the `deploy-to-foro` skill pushes this to GitHub and gets it live. Before
replacing the scaffolded example with real tools, the `design-mcp-tools` skill
covers what makes them cheap to carry and easy for a model to pick correctly.
If the server should answer with an interface rather than JSON, a card or a
list rendered in the chat, that is the `design-mcp-view` skill.
