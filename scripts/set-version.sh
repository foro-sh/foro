#!/usr/bin/env bash
# Stamp a release version into both SDK manifests and their lockfiles.
#
# release-please owns the version number (CHANGELOG + the manifest) but not
# the lockfiles. This runs on the Release PR branch so the bumped files land
# on that PR before merge - and therefore inside the tag. Extra-filing
# package.json from release-please would desync package-lock.json and fail
# `npm ci` on the PR.
set -euo pipefail

VERSION="${1:?usage: set-version.sh <version>}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Rewrites only the first `version = "..."` at column 0, which is
# [project].version. A dependency pin written the same way further down the
# file must not be touched - and if the anchor ever stops matching exactly
# once, fail loudly rather than release an unbumped package.
python3 - "$VERSION" "$ROOT/packages/python/pyproject.toml" <<'PY'
import re
import sys

version, path = sys.argv[1], sys.argv[2]
with open(path) as handle:
    source = handle.read()

new, count = re.subn(
    r'(?m)^version = "[^"]*"$', f'version = "{version}"', source, count=1
)
if count != 1:
    sys.exit(f"{path}: expected one top-level version line, rewrote {count}")

with open(path, "w") as handle:
    handle.write(new)
PY

# `npm version` rather than editing package.json directly: it keeps
# package-lock.json in step, and `npm ci` in the publish workflow hard-fails
# when the two disagree.
npm --prefix "$ROOT/packages/typescript" version "$VERSION" \
  --no-git-tag-version --allow-same-version >/dev/null

# uv.lock records the project's own version, so rewriting pyproject.toml
# without relocking leaves the two disagreeing and `uv sync --frozen` fails.
# It hides easily: `uv run` silently relocks, so local work keeps passing
# while the committed lockfile is stale - and `foro check`, the contract this
# SDK enforces on other repos, reports lockfile_out_of_sync against its own.
uv lock --project "$ROOT/packages/python" --quiet

# The minimal-fastmcp fixture depends on this package through an editable
# path source, so its lockfile records our version too and goes stale on the
# same bump - which is how it drifted to 0.1.0 while the package reached
# 0.8.0. It's the only fixture that needs this: no other one has a
# [tool.uv.sources] pointing here, and lockfile-out-of-sync is deliberately
# stale, so relocking fixtures as a group would destroy the case it tests.
uv lock --project "$ROOT/packages/python/tests/fixtures/minimal-fastmcp" --quiet

echo "set version to $VERSION"
