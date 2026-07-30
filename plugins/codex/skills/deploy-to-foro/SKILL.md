---
name: deploy-to-foro
description: Get a local foro.sh MCP server live at a public https://<slug>.foro.sh URL with `foro deploy`. Use when the user wants to deploy, ship, publish, or go live with a foro.yaml project on foro.sh, mentions `foro deploy`, or asks how to get their MCP server onto a public URL. Assumes the repo passes `foro check` (see create-foro-project). For a deploy that already failed, use debug-a-foro-deploy instead.
---

# Deploy a project to foro.sh

`foro deploy` takes the directory you just ran with `foro dev` and puts it live.
No GitHub repo, no push, no dashboard round trip for the first deploy.

There is exactly one step you cannot take for the user — signing in. Do that
first, get out of their way for it, and the rest is one command.

## 1. Make sure there's a credential

```bash
uvx foro auth status
```

Exits 0 with the account and workspace when a token is live, and exits 1 when
there isn't one. Two ways forward:

- **`FORO_TOKEN` is already in the environment** → nothing to do; `auth status`
  reports `$FORO_TOKEN` as the source. This is the case in CI and in a
  pre-authorized agent sandbox, and it's the only way this path runs unattended.
- **Not logged in** → run `uvx foro auth login`. It prints a one-time code and
  a URL, then waits.

**When you run `foro auth login`, stop and hand it to the user.** It is a device
flow: the code has to be approved in a browser by the person who owns the
account, and no amount of retrying makes that happen from here. Show them the
code and the URL verbatim, say you are waiting on their approval, and continue
only once it succeeds. Do not invent a token, do not offer a workaround, and do
not report progress you haven't seen.

The token is workspace-scoped, chosen at approval time. A user with two
workspaces logs in twice; there is no workspace-switch command.

## 2. Deploy

```bash
uvx foro deploy
```

That is the whole thing. It runs `foro check` first (so nothing that can't build
gets uploaded), packages the working tree, ships it, and streams the build until
the server is live or has failed. Indented lines in the output are raw
`docker build` output; unindented ones are the deploy narrative.

`Ctrl+C` detaches without cancelling the deploy — say that if it comes up,
rather than implying the deploy died.

### What gets deployed depends on the project's source

Don't guess this out loud. The CLI tells you, and the difference matters:

| Situation | What `foro deploy` does |
| --- | --- |
| Directory not linked to a project | Creates an **upload** project from the working tree, and links this directory to it |
| Linked, `source: upload` | Uploads the working tree again, then deploys |
| Linked, `source: github` | Builds from the repo **branch** — uncommitted and unpushed work is *not* in that build, and the CLI warns about it |

That last row is the one to read out loud when it happens. A user watching a
`github`-source deploy of a tree with uncommitted changes is about to ask why
their change isn't live; the warning is the answer, so don't scroll past it.

`--upload` / `--repo` force either path when the inference is wrong. `--detach`
skips the streaming. `--project <slug>` targets a project this directory isn't
linked to.

### The link, and redeploying

The first deploy writes `.foro/project.json` (`{host, slug, workspace}`), which
is gitignored and per-clone. Redeploying is `uvx foro deploy` again — same slug,
same URL. `foro link <slug>` adopts a project created in the dashboard, and
`foro unlink` forgets it.

This is deliberately **not** in `foro.yaml`: that file is the committed, shared
build contract, and a slug baked into it would make anyone who forks the repo
deploy into the original owner's project.

## 3. Secrets are still a dashboard step

If the server reads `foro.secret("NAME")`, that value has to be set in the
project's Secrets tab on the dashboard before the server will start. There is no
`foro secrets` command yet (issue #37), so this is a genuine hand-off: name the
exact keys the code reads and tell the user where to put them.

Never put a secret in `foro.yaml`, in the repo, or in a committed `.env` —
`foro deploy` excludes `.env*` from the archive for exactly this reason.

## 4. Verify the live URL before saying it works

A deploy reporting `live` means the container started and passed a TCP health
check. That is not evidence the server answers MCP with the tools it should
have. Same rule as local: don't claim success on a banner.

```bash
curl -sS -X POST https://<slug>.foro.sh/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

A real `tools/list` naming the tools you built is the proof. If it doesn't
answer, the deploy isn't done — go to `debug-a-foro-deploy`.

## The URL is a generated slug

The server lives at `https://<slug>.foro.sh`, where the slug is randomly
generated (`adjective-noun-4char`, e.g. `swift-harbor-a3f2`) and **immutable**.
It is not derived from `foro.yaml`'s `name`, which is display-only. Never promise
a specific subdomain — read the real one out of the deploy output.

## Looking things up

`foro-docs.read_doc("connect")` and `foro-docs.read_doc("secrets")` carry the
current walkthroughs (`foro-docs.list_docs()` for every slug). If the docs
server isn't reachable, **say so** and continue from this skill's content —
don't quietly fall back to half-remembered details and present them as current.

## Done when

- `foro deploy` reported the deploy as live.
- `https://<slug>.foro.sh/mcp` returned a real `tools/list` with the expected
  tools in it.
- The user has the actual slug URL, not a predicted one.

When a deploy fails instead, that's `debug-a-foro-deploy` — which of the two log
streams to read, and what each failure mode looks like.
