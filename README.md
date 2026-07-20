# Foro SDK monorepo

This repository publishes the `foro` SDK - a Python package (and, eventually,
a TypeScript one) for building and deploying MCP servers on
[foro.sh](https://foro.sh).

## Deploy with Foro

```bash
uvx foro init my-server && cd my-server
uvx foro dev
git init && git add -A && git commit -m "init" && gh repo create --push
# -> foro.sh dashboard: pick the repo, add secrets, Deploy
```

See [`packages/python/README.md`](packages/python/README.md) for the full
quickstart, the CLI (`foro init` / `check` / `dev`), and the runtime API
(`foro.run`, `foro.secret`).
[`foro-sh/todo-mcp`](https://github.com/foro-sh/todo-mcp) is a live example
project built this way.

## Layout

- `packages/python/` — Python package published with `uv`
- `packages/typescript/` — TypeScript package published to npm
- `.github/workflows/` — publishing workflows for PyPI and npm

## Goals

- Reserve the `foro` package name in both ecosystems
- Keep the SDKs versioned together
- Make it easy to add generated clients or shared API specs later
