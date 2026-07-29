---
name: create-foro-project
description: Scaffold a deployable foro.sh MCP server from scratch. Use when the user wants to create, start, or bootstrap a new MCP server to deploy on foro.sh, mentions `foro init`, or asks how to make a repo deployable to foro.sh. Produces a working local server that passes foro.sh's deploy checks; hand off to `/foro:deploy-to-foro` to get it live.
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

1. **Python + `uv` only.** foro.sh v0 builds Python projects managed with
   `uv` (a `pyproject.toml` + committed `uv.lock`). No other runtime deploys
   yet. If the user wants a TypeScript/Node server, tell them it isn't
   deployable on foro.sh yet rather than scaffolding something that can't ship.
2. **Secrets go in the dashboard, never in the repo.** API keys and tokens are
   added in the project's Secrets tab on the foro.sh dashboard and arrive as
   environment variables at deploy time. Never commit a secret, never put one
   in `foro.yaml`. In code, read them with `foro.secret("NAME")`, which raises
   a dashboard-actionable error when the secret is unset.

## Steps

### 1. Scaffold with `foro init`

Run the CLI (no need to add `foro` to the project's own dependencies):

```bash
uvx foro init <name>
cd <name>
```

`foro init` writes a working [FastMCP](https://gofastmcp.com) server, a
`foro.yaml`, and `pyproject.toml` + `uv.lock`. Read the generated files and
**explain what they contain** — the entrypoint, the example tool, and how
`foro.run(...)` starts the server — rather than regenerating them by hand. To
add `foro.yaml` to an existing repo instead, run `uvx foro init` with no name
argument from the repo root.

### 2. Explain `foro.yaml` (look up the current fields, don't hardcode them)

`foro.yaml` sits at the repo root and declares how the platform builds and runs
the server. The field list changes over time, so pull the current one from the
docs MCP instead of trusting anything memorised:

- Call `foro-docs.read_doc("foro-yaml")` for the authoritative, current field
  reference. (Use `foro-docs.list_docs()` to see every available doc slug, and
  `foro-docs.search_docs("...")` to find one by keyword.)

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
- The user understands: Python + `uv` only, secrets live in the dashboard, and
  the deployed URL is a generated slug, not `foro.yaml`'s `name`.

Next: `/foro:deploy-to-foro` pushes this to GitHub and gets it live.
