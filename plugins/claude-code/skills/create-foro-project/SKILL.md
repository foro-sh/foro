---
name: create-foro-project
description: Scaffold a deployable foro.sh MCP server from scratch. Use when the user wants to create, start, or bootstrap a new MCP server to deploy on foro.sh, mentions `foro init`, or asks how to make a repo deployable to foro.sh. Produces a working local server that passes foro.sh's deploy checks; hand off to the deploy-to-foro skill to get it live.
---

# Create a foro.sh project

Take the user from an empty folder to a `foro.yaml`-carrying MCP server that
runs locally *exactly* the way foro.sh will run it. Do not hand-write the
server or the manifest — the `foro` CLI scaffolds a version that is guaranteed
to pass the platform's deploy contract, and your job is to run it and explain
what it produced.

## State these two constraints first

They are the top two reasons a first deploy fails, so say them before writing
anything:

1. **Python only.** foro.sh v0 deploys Python MCP servers. Any of `uv`, PDM,
   Poetry, pipenv, or a plain `requirements.txt` works — the platform detects
   which from the lockfile or `pyproject.toml` in the build directory. `uv` is
   the default and what `foro init` scaffolds, so prefer it for a new project,
   but never tell someone their existing Poetry or `requirements.txt` project
   can't ship. If the user wants a TypeScript/Node server, that is the real
   limit: say it isn't deployable on foro.sh yet rather than scaffolding
   something that can't ship.
2. **Secrets go in the dashboard, never in the repo.** API keys and tokens are
   added in the project's Secrets tab on the foro.sh dashboard and arrive as
   environment variables at deploy time. Never commit a secret, never put one
   in `foro.yaml`. In code, read them with `foro.secret("NAME")`, which raises
   a dashboard-actionable error when the secret is unset.

## Steps

### 1. Scaffold with `foro init`

Run the CLI (no need to add `foro` to the project's own dependencies; `uvx`
runs it whatever the project itself is managed with):

```bash
uvx foro init <name>
cd <name>
```

`foro init` writes a working [FastMCP](https://gofastmcp.com) server, a
`foro.yaml`, and `pyproject.toml` + `uv.lock`. Read the generated files and
**explain what they contain** — the entrypoint, the example tool, and how
`foro.run(...)` starts the server — rather than regenerating them by hand.

If the user already has a working MCP server rather than an empty folder, this
is the wrong skill: use `add-foro-to-existing-server`, which handles the
transport conversion that porting actually turns on.

### 2. Explain `foro.yaml` (look up the current fields, don't hardcode them)

`foro.yaml` sits at the repo root and declares how the platform builds and runs
the server. The field list changes over time, so pull the current one from the
docs MCP instead of trusting anything memorised:

- Call `foro-docs.read_doc("foro-yaml")` for the authoritative, current field
  reference. (Use `foro-docs.list_docs()` to see every available doc slug, and
  `foro-docs.search_docs("...")` to find one by keyword.)

One field the docs page doesn't list but the platform does validate:
`dependency_manager` (`uv`, `pdm`, `poetry`, `pipenv`, or `uv-pip`). Detection
is automatic, so leave it out — reach for it only when a repo is genuinely
ambiguous and the platform picks the wrong one.

The one thing to make unmistakable: **`name` in `foro.yaml` is a display name
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
- The user understands: Python only (any of the five dependency managers),
  secrets live in the dashboard, and the deployed URL is a generated slug, not
  `foro.yaml`'s `name`.

Next: the `deploy-to-foro` skill pushes this to GitHub and gets it live. Before
replacing the scaffolded example with real tools, the `design-mcp-tools` skill
covers what makes them cheap to carry and easy for a model to pick correctly.
