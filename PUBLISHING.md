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

If an upload fails after the release was tagged, republish from the Actions tab
rather than cutting another release. Dispatching builds the branch head, which
after a release is the commit carrying the version bump.

- **PyPI** — dispatch **Publish Python SDK**.
- **npm** — dispatch **Semantic Release** with `publish_npm` checked. It skips
  the release itself and only runs the npm upload. Dispatching *Publish
  TypeScript SDK* directly is not possible, by design — see above.

## Credentials

Both registries use trusted publishing (OIDC). There is no stored token for
either, so nothing expires and no 2FA-bypass token is needed.

| Registry | Publisher workflow filename | Environment |
| --- | --- | --- |
| PyPI | `semantic-release.yml` (automatic) **and** `publish-python.yml` (manual) | `pypi` |
| npm | `semantic-release.yml` — one only | `npm` |

The environment must match the `environment:` on the job performing the
upload.

npm permits only **one** trusted-publisher filename per package, and resolves
the *calling* workflow — so `semantic-release.yml` is the only filename that
can ever authenticate an npm publish. Every npm upload, automatic or manual,
is therefore called from that file. `publish-typescript.yml` is
`workflow_call`-only for this reason: triggered directly it would fail
`ENEEDAUTH`, so it deliberately offers no button that cannot work.

PyPI allows several publishers, so it keeps a genuine manual path.

They land on the same table for opposite reasons. PyPI [cannot authorize an
upload inside a reusable workflow][pypi-reusable] at all, so its steps are
duplicated into `semantic-release.yml`. npm can, but [resolves the *calling*
workflow's filename][npm-reusable] rather than the one holding the publish
step — so the reusable call is fine, and npm simply sees `semantic-release.yml`
on the automatic path.

npm additionally requires npm ≥ 11.5.1, Node ≥ 22.14, and `id-token: write` on
**both** the calling and the called workflow. `publish-typescript.yml` asserts
the npm version explicitly, so a runner image shipping an older npm fails with
a legible message instead of an auth error that looks like a broken publisher.

[npm-reusable]: https://docs.npmjs.com/trusted-publishers

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
