# Foro SDK monorepo

This repository is a starting point for publishing both a Python SDK and a TypeScript SDK under the Foro brand.

## Suggested layout

- `packages/python/` — Python package published with `uv`
- `packages/typescript/` — TypeScript package published to npm
- `.github/workflows/` — publishing workflows for PyPI and npm

## Goals

- Reserve the `foro` package name in both ecosystems
- Keep the SDKs versioned together
- Make it easy to add generated clients or shared API specs later
