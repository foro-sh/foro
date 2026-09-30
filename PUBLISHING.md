# Publishing

Feature PRs merge to `main` without publishing. release-please opens (or
updates) one Release PR that accumulates them. Merging *that* PR cuts the
version and publishes.

Nothing is published from a pull request, including the Release PR itself.

## Package names

| Registry | Package | Source |
| --- | --- | --- |
| PyPI | `foro` | `packages/python` |
| npm | `@foro-sh/foro` | `packages/typescript` |

## What happens on merge to main

`.github/workflows/semantic-release.yml` (Actions name **Release**; the
filename is load-bearing for trusted publishing) runs
googleapis/release-please-action:

- An ordinary `feat`/`fix` merge **updates the Release PR**
  (`chore(main): release 0.x.y`) with the combined changelog. Docs, `ci`,
  and `chore` commits do not open one.
- Merging the Release PR **creates the tag and GitHub release**. Tests then
  run on that commit, and `publish-python` / `publish-typescript` each run
  only when that package's directory changed in the merged range.

A separate workflow (`.github/workflows/stamp-release.yml`) runs on the
Release PR branch and invokes `scripts/set-version.sh` so both manifests and
their lockfiles land on the PR before you merge it. Extra-filing
`package.json` from release-please would desync `package-lock.json` and fail
`npm ci`.

So a Release PR whose source commits only touched `packages/python`
publishes to PyPI and leaves npm alone; a docs-only stretch of `main`
opens no Release PR at all.

Both publish jobs build the exact tagged commit, not a branch name, so a
merge landing moments later can't be picked up by mistake.

Merge the Release PR with a merge commit or squash. Do not rebase-merge it:
release-please identifies the release from the merged pull request, and a
rebase drops that signal.

Commitlint now runs as `Tests / Lint commit messages`. If branch protection
still requires `Semantic Release / Lint commit messages`, update that check.

The npm upload is a reusable-workflow call into `publish-typescript.yml`. The
PyPI upload cannot be — see [Credentials](#credentials) — so those steps are
duplicated inside `semantic-release.yml`. If you change one, change both.

### Change detection

Measured from the previous tag to **`HEAD^`** (main before the release
commit). The release commit rewrites both manifests, so measuring `HEAD`
would mark every package as changed on every release.

## Versioning: staying on 0.x

The SDKs and CLI are pre-stable, so releases must stay on `0.x`.

release-please derives the next version from `.release-please-manifest.json`
(bootstrapped from the last tag). Under semver a breaking change would
normally jump to `1.0.0`. To prevent that, `release-please-config.json` sets:

```json
"bump-minor-pre-major": true,
"bump-patch-for-minor-pre-major": false
```

So while pre-stable:

| Commit | Bump |
| --- | --- |
| `fix:` | patch — `0.1.0` → `0.1.1` |
| `feat:` | minor — `0.1.0` → `0.2.0` |
| `feat!:` / `BREAKING CHANGE:` | minor — `0.1.0` → `0.2.0` |

**When the SDKs are ready to go stable**, drop `bump-minor-pre-major`. The
next breaking change then bumps to `1.0.0` on its own.

## Manual publishing

If an upload fails after the release was tagged, republish from the Actions tab
rather than cutting another release. Dispatching builds the branch head, which
after a release is the commit carrying the version bump.

- **PyPI** — dispatch **Publish Python SDK**.
- **npm** — dispatch **Release** with `publish_npm` checked. It skips
  release-please and only runs the npm upload. Dispatching *Publish
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
