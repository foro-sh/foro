# Foro TypeScript SDK

This package is the TypeScript SDK for Foro.

## `@foro-sh/foro/manifest-cases`

The shared `foro.yaml` validation table, as typed data. Foro's Python
`_manifest.py` is a port of [foro-sh/platform]'s
`apps/api/src/services/manifest.ts`, so both implementations run this same
table to guarantee they never disagree about what a valid manifest is — if
they did, `foro check` would pass locally and the deploy would fail.

```ts
import { manifestCases } from '@foro-sh/foro/manifest-cases'

for (const { name, yaml, expect } of manifestCases) {
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
