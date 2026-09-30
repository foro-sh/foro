# Foro TypeScript SDK

This package is the TypeScript SDK for Foro.

## `skills(server, dir = 'skills')`

Serves every `<dir>/<name>/SKILL.md` as an
[Agent Skill over MCP](https://modelcontextprotocol.io/extensions/skills/overview):
the `io.modelcontextprotocol/skills` capability, `skills/list` and `skills/get`
with a SHA-256 manifest per skill, and each file over `resources/read` at
`skill://<name>/<file>`.

```ts
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { skills } from '@foro-sh/foro'

const server = new McpServer({ name: 'my-server', version: '0.1.0' })
skills(server) // before server.connect()
```

Needs `@modelcontextprotocol/sdk` 1.31+ and `zod` 4 alongside it. The
directory is scanned once per process, and a skill whose frontmatter `name`
isn't its directory name throws at startup rather than being served.

## `@foro-sh/foro/manifest-cases`

The shared project-config validation table, as typed data. Foro's Python
`_manifest.py` is a port of [foro-sh/platform]'s
`apps/api/src/services/manifest.ts`, so both implementations run this same
table to guarantee they never disagree about what a valid `pyproject.toml` or
`package.json` is — if they did, `foro check` would pass locally and the deploy
would fail.

```ts
import { manifestCases } from '@foro-sh/foro/manifest-cases'

for (const { name, files, expect } of manifestCases) {
  // write `files` into an empty directory, then validate it
  // expect is { ok: true } or { ok: false, reason: ManifestRejectionReason }
}
```

Each case asserts only accept/reject and the rejection reason; the resolved
defaults an implementation produces stay covered by its own tests.

The cases live in `packages/python/src/foro/manifest-cases.json` — the single
source of truth — and are inlined into this package at build time. Add cases
there, not here.

[foro-sh/platform]: https://github.com/foro-sh/platform

## Development

```bash
npm install
npm run build
```
