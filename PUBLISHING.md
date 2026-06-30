# Publishing checklist

The package names are currently available:

- npm: `foro`
- PyPI: `foro`

## Before the first publish

1. Create npm and PyPI accounts.
2. Create an npm automation token.
3. Add this GitHub repository secret:
   - `NPM_TOKEN`
4. Configure PyPI trusted publishing for this repository and project.
5. Bump the versions in:
   - `packages/typescript/package.json`
   - `packages/python/pyproject.toml`
6. Trigger the publish workflows from the GitHub Actions tab.

## Local sanity checks

```bash
npm --prefix packages/typescript install
npm --prefix packages/typescript run build

python3 -m compileall packages/python/src
```
