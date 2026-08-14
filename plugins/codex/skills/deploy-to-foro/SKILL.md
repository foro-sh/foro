---
name: deploy-to-foro
description: Get a local foro.sh MCP server live at a public https://<slug>.foro.sh URL. Use when the user wants to deploy, ship, publish, or go live with a project on foro.sh, or when a foro.sh deploy has failed and they need help reading the logs. Assumes the repo already passes `foro check` (see the create-foro-project skill).
---

# Deploy a project to foro.sh

Get a local, `foro check`-passing project to a public `https://<slug>.foro.sh`
URL. Deploying is a GitHub push plus a few clicks in the dashboard — be honest
about which parts are a browser step, and don't fake a CLI deploy.

## Preflight

Confirm the repo is actually deployable before pushing:

```bash
uvx foro check
```

If it doesn't pass, stop and fix that first (the `create-foro-project` skill
covers scaffolding and the constraints). A repo `foro check` flags will not
deploy. Warnings are worth reading too — they don't block a deploy, but they
name what will be slow or non-reproducible about it.

## 1. Get the code on GitHub

foro.sh deploys from a GitHub repo, so it needs to exist there first:

```bash
git init
git add -A
git commit -m "init"
gh repo create --push        # creates the GitHub repo and pushes in one step
```

Commit the lockfile — `uv.lock`, `pdm.lock`, `poetry.lock`, or `Pipfile.lock`,
whichever your dependency manager writes. Without one the build still runs, but
as a slower unlocked install with no reproducibility guarantee. A lockfile that
is *out of sync* with `pyproject.toml` is worse than none: the build installs
with `--frozen` and fails outright.

## 2. Deploy from the dashboard (this part is a browser step)

There is **no deploy API for users yet** — deploying happens in the foro.sh
dashboard, not the CLI. Don't pretend a command does it. Walk the user through:

1. Sign in to the foro.sh dashboard with GitHub.
2. Pick the repo you just pushed.
3. Add any secrets the server needs in the **Secrets** tab (the same names your
   code reads via `foro.secret("NAME")`). Secrets live here, never in the repo.
4. Click **Deploy**.

For the current connect/deploy walkthrough and screenshots, read the docs MCP:
`foro-docs.read_doc("connect")` and `foro-docs.read_doc("secrets")` (use
`foro-docs.list_docs()` to see all slugs).

## 3. The result: a generated URL, not a name you choose

About a minute after Deploy, the server is live at:

```
https://<slug>.foro.sh
```

The slug is **randomly generated** (`adjective-noun-4char`, e.g.
`swift-harbor-a3f2`) and **immutable**. It is not derived from the project's
`name`. Do not promise the user a specific subdomain — read the real slug off
the dashboard once the deploy finishes.

## When a deploy fails

foro.sh splits logs into two streams — check the right one:

- **Build log** — raw `docker build` output. Look here for dependency/lockfile
  problems: a stale lockfile, a package that won't install, a bad
  `runtime` and `runtime_version`.
- **Deploy log** — the orchestration narrative: clone, config validation,
  container start, health check, and the failure reason. Look here for a wrong
  `entrypoint`, a server not listening on `0.0.0.0:$PORT`, or a health
  check that timed out.

Usual suspects, in rough order of frequency:

1. **Stale lockfile** — the lockfile no longer matches `pyproject.toml`, so the
   frozen install fails. Re-lock (`uv lock`, `poetry lock`, …), commit, push.
2. **Wrong entry file** — the file foro starts must be the one that calls
   `foro.run(...)`.
3. **Unset secret** — the code calls `foro.secret("NAME")` but `NAME` wasn't
   added in the Secrets tab. Add it and redeploy.
4. **Server doesn't bind correctly** — it must listen on `0.0.0.0:$PORT`,
   which `foro.run()` does for you; a hand-rolled `run()` that binds
   `127.0.0.1` or a fixed port will fail the health check.

Reproduce most of these locally with `uvx foro dev` before pushing again — it
runs the server the same way the platform does, so a failure shows up in
seconds instead of as a 60-second cloud health-check timeout.

## Done when

The dashboard shows the deploy succeeded and `https://<slug>.foro.sh` serves a
real MCP response. Report the actual slug URL, not a predicted one.
