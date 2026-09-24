---
name: deploy-to-foro
description: Get a local foro.sh MCP server live at a public https://<slug>.foro.sh URL with `foro deploy`. Use when the user wants to deploy, ship, publish, or go live with a project on foro.sh, mentions `foro deploy`, or asks how to get their MCP server onto a public URL. Assumes the repo already passes `foro check` (see the create-foro-project skill). For a deploy that already failed, use debug-a-foro-deploy instead.
---

# Deploy a project to foro.sh

`foro deploy` takes the directory you just ran with `foro dev` and puts it live.
No GitHub repo, no push and no dashboard round trip for the first deploy.

There is exactly one step you cannot take for the user: signing in. Do that
first, get out of their way for it, and the rest is one command.

## Preflight

```bash
uvx foro check
```

If it doesn't pass, stop and fix that first (the `create-foro-project` skill
covers scaffolding and the constraints). `foro deploy` runs the same check and
refuses to upload a tree that fails it. Warnings are worth reading too — they
don't block a deploy, but they name what will be slow or non-reproducible about
it.

Commit or at least write the lockfile — `uv.lock`, `poetry.lock`,
`package-lock.json`, or whichever your dependency manager writes. A lockfile
that is *out of sync* with `pyproject.toml` or `package.json` is worse than
none: the build installs exactly what it pins. `npm ci` refuses outright; `uv
sync --frozen` succeeds without the new dependency, and the server dies on
import. After any dependency change, re-lock (`uv lock`, `npm install`, …).

## 1. Make sure there's a credential

```bash
uvx foro auth status
```

Exits 0 with the account and workspace when a token is live, 1 when there
isn't one.

- **`FORO_TOKEN` is set** → nothing to do; `auth status` reports it as the
  source. This is the case in CI and in a pre-authorized agent sandbox, and it's
  the only way this path runs unattended.
- **Not logged in** → run `uvx foro auth login`. It prints a one-time code and
  a URL, then waits.

**When you run `foro auth login`, stop and hand it to the user.** It is a device
flow: the code has to be approved in a browser by the person who owns the
account, and no amount of retrying makes that happen from here. Show them the
code and the URL verbatim, say you are waiting on their approval, and continue
only once it succeeds. Do not invent a token, and do not report progress you
haven't seen.

The token is scoped to the workspace chosen at approval time. A user with two
workspaces logs in twice; there is no workspace-switch command.

## 2. Deploy

```bash
uvx foro deploy
```

It runs `foro check`, packages the working tree, ships it, and streams the build
until the server is live or has failed. Lines prefixed `│` are raw `docker
build` output; the rest is the deploy narrative. `Ctrl+C` detaches without
cancelling the deploy — say that if it comes up, rather than implying the
deploy died.

What gets deployed depends on the project's source, and the CLI says which:

| Situation | What `foro deploy` does |
| --- | --- |
| Directory not linked to a project | Creates an **upload** project from the working tree and links this directory to it |
| Linked, `source: upload` | Uploads the working tree again, then deploys |
| Linked, `source: github` | Builds from the repo **branch** — uncommitted and unpushed work is *not* in that build, and the CLI warns about it |

Read that last warning out loud when it appears: it's the answer to "why isn't
my change live" before the user asks.

`--upload` / `--repo` force either path, `--detach` skips the streaming, and
`--project <slug>` targets a project this directory isn't linked to.

The upload leaves out `.git`, `.venv`, `node_modules`, `dist`, `.foro` and
`.env*` (except `.env.example`), plus anything git ignores.

### The link, and redeploying

The first deploy writes `.foro/project.json`, which is per-clone and belongs in
`.gitignore` (projects from `foro init` already ignore it). Redeploying is
`uvx foro deploy` again — same slug, same URL. `foro link <slug>` adopts a
project created in the dashboard, and `foro unlink` forgets it.

If the dashboard already has a project for this repo, `foro link` it rather
than deploying a second one.

## 3. Secrets are a dashboard step

Every name the server reads — `foro.secret("NAME")` in Python,
`process.env.NAME` in Node — has to be set in the project's **Secrets** tab
before the server will start. There is no CLI command for this yet, so it's a
genuine hand-off: name the exact keys the code reads and tell the user where to
put them. Never put a secret in the repo or a committed `.env`.

`foro-docs.read_doc("secrets")` has the current walkthrough (without the docs
MCP: https://foro.sh/docs/secrets).

## 4. Verify the live URL before saying it works

A deploy reporting `live` means the container started and passed a health
check. That is not evidence the server answers MCP with the tools it should
have.

```bash
uvx foro verify https://<slug>.foro.sh
```

It opens a real MCP session and lists the tools. A tool list naming the tools
you built is the proof; anything else goes to `debug-a-foro-deploy`.

## The URL is a generated slug

The slug is randomly generated (`adjective-noun-4char`, e.g.
`swift-harbor-a3f2`) and **immutable**. It is not derived from the project's
`name`. Never promise a specific subdomain — read the real one out of the
deploy output.

## Done when

- `foro deploy` reported the deploy as live.
- `foro verify` listed the expected tools.
- The user has the actual slug URL, not a predicted one.
