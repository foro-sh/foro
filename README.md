<div align="center">

# foro

**Sovereign infrastructure for MCP servers.**

Push a Git repo with a `foro.yaml` to [foro.sh](https://foro.sh) and get a
stable `https://<slug>.foro.sh` URL in about a minute — no Dockerfile, no YAML
pipeline, no cloud console. This repository is the SDK that makes a repo
deployable in the first place.

[![PyPI](https://img.shields.io/pypi/v/foro?label=PyPI&color=3775A9)](https://pypi.org/project/foro/)
[![npm](https://img.shields.io/npm/v/%40foro-sh%2Fforo?label=npm&color=CB3837)](https://www.npmjs.com/package/@foro-sh/foro)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

[Quickstart](#quickstart) ·
[Packages](#packages) ·
[Example](#example) ·
[Contributing](#contributing)

</div>

---

## What is Foro?

foro.sh takes a locally running [MCP](https://modelcontextprotocol.io) server
and turns it into a publicly reachable one: sign in with GitHub, pick a repo,
add secrets, click Deploy. The platform builds it, runs it in an isolated
container, and TLS-terminates it behind a stable subdomain.

The `foro` package in this repository is the other half of that contract —
the part that runs in *your* repo, before and during a deploy:

- **`foro init` / `foro check` / `foro dev`** — scaffold a server that's
  guaranteed to pass foro.sh's deploy checks, then validate and run it
  locally *exactly* the way the platform will. If `foro dev` says it would
  pass the health check, it will pass deployed.
- **`foro.run(server)`** — the one correct way to start your server: real
  streamable HTTP, bound on all interfaces, on the port foro.sh expects.
  Identical locally and deployed, so there's no "works on my machine" gap.
- **`foro.secret(name)`** — read a required secret with an error that tells
  you where to actually set it, instead of a bare `KeyError`.

None of this is a framework. It's a thin, dependency-free shim over
[FastMCP](https://gofastmcp.com) that encodes the platform's deploy contract,
so the failures that used to show up as a silent 60-second health-check
timeout show up instantly, locally, with a reason.

## Quickstart

```bash
uvx foro init my-server && cd my-server
uvx foro dev
git init && git add -A && git commit -m "init" && gh repo create --push
# -> foro.sh dashboard: pick the repo, add secrets, Deploy
```

See [`packages/python/README.md`](packages/python/README.md) for the full CLI
reference, the runtime API, and how secrets flow from the dashboard into your
server's environment.

## Packages

| Package | Registry | Role |
| --- | --- | --- |
| [`packages/python`](packages/python) | [![PyPI](https://img.shields.io/pypi/v/foro?label=%20)](https://pypi.org/project/foro/) | Primary SDK - Python is the only supported runtime in foro.sh v0 |
| [`packages/typescript`](packages/typescript) | [![npm](https://img.shields.io/npm/v/%40foro-sh%2Fforo?label=%20)](https://www.npmjs.com/package/@foro-sh/foro) | Name reserved, not yet implemented |

Both packages are versioned and released together via
[semantic-release](https://semantic-release.gitbook.io/); see
[`CHANGELOG.md`](CHANGELOG.md) for the release history.

## Example

[`foro-sh/todo-mcp`](https://github.com/foro-sh/todo-mcp) is a small, stateful
todo-list MCP server built the way described above — every new foro.sh
workspace gets a deployed copy of it to poke at before deploying anything of
your own.

## Contributing

Issues and pull requests are welcome. Commit messages must follow
[Conventional Commits](https://www.conventionalcommits.org/)
(`<type>(scope): description`) — it's what drives the automated changelog and
version bump on every merge to `main`, and it's enforced on PRs by commitlint.

```bash
npm install                          # commitlint + semantic-release tooling
cd packages/python && uv sync && uv run pytest
```

## License

[MIT](LICENSE)
