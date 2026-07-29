# Publishing

Both SDKs publish automatically on merge to `main`. Nothing is published from
a pull request.

## Package names

| Registry | Package | Source |
| --- | --- | --- |
| PyPI | `foro` | `packages/python` |
| npm | `@foro-sh/foro` | `packages/typescript` |

## What happens on merge

`.github/workflows/semantic-release.yml` runs:

1. **commitlint** — rejects commits that don't follow Conventional Commits.
2. **release** — records which packages changed in the merged range, then runs
   semantic-release. If the commits warrant a release, it stamps the new
   version into both manifests (`scripts/set-version.sh`, invoked from the
   exec plugin's `prepareCmd`), commits them as `chore(release):`, tags, and
   publishes GitHub release notes.
3. **publish-python / publish-typescript** — each runs only when a release was
   cut *and* that package's directory changed in the merged range.

So a PR touching only `packages/python` publishes to PyPI and leaves npm
alone; a PR touching only docs publishes nothing.

Both publish jobs build the exact commit carrying the version bump, not a
branch name, so a merge landing moments later can't be picked up by mistake.

The npm upload is a reusable-workflow call into `publish-typescript.yml`. The
PyPI upload cannot be — see [Credentials](#credentials) — so those steps are
duplicated inside `semantic-release.yml`. If you change one, change both.

### Change detection

Measured over the push range (`github.event.before..HEAD`) **before**
semantic-release runs. That ordering matters: the `chore(release):` commit
rewrites both manifests, so measuring afterwards would mark every package as
changed on every release.

## Versioning: staying on 0.x

The SDKs and CLI are pre-stable, so releases must stay on `0.x`.

semantic-release derives the next version from the most recent git tag, and
under semver a breaking change would normally jump to `1.0.0`. To prevent
that, `.releaserc.json` maps breaking changes to a **minor** bump:

```json
"releaseRules": [{ "breaking": true, "release": "minor" }]
```

So while pre-stable:

| Commit | Bump |
| --- | --- |
| `fix:` | patch — `0.1.0` → `0.1.1` |
| `feat:` | minor — `0.1.0` → `0.2.0` |
| `feat!:` / `BREAKING CHANGE:` | minor — `0.1.0` → `0.2.0` |

**When the SDKs are ready to go stable**, drop that `releaseRules` entry. The
next breaking change then bumps to `1.0.0` on its own.

## Manual publishing

Both publish workflows keep a `workflow_dispatch` trigger for recovery — if a
publish job fails after the release was tagged, re-run it from the Actions tab
rather than cutting another release. Dispatching builds the branch head, which
after a release is the commit with the bumped version.

## Credentials

- **PyPI** — trusted publishing (OIDC), no stored token.
- **npm** — `NPM_TOKEN` repository secret, used by the `npm` environment.

### Why the PyPI upload is duplicated

PyPI matches an upload against a trusted publisher pinned to a specific
workflow filename, and [it cannot authorize an upload that runs inside a
reusable workflow][pypi-reusable]:

> Reusable workflows cannot currently be used as the workflow in a Trusted
> Publisher.

So the automatic PyPI upload has to live in `semantic-release.yml` itself,
duplicating the steps in `publish-python.yml` rather than calling it. **Both
files need their own trusted publisher configured on PyPI** — one for the
automatic path, one for manual recovery. npm has no such restriction, so
`publish-typescript.yml` is called as a reusable workflow.

[pypi-reusable]: https://docs.pypi.org/trusted-publishers/troubleshooting/

## Local sanity checks

```bash
npm --prefix packages/typescript install
npm --prefix packages/typescript run build

cd packages/python && uv run pytest
```
