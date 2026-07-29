#!/usr/bin/env bash
# Stamp a release version into both SDK manifests.
#
# semantic-release owns the version number but ships no Python plugin, so the
# Python manifest has to be rewritten by hand. This runs from the release's
# `prepareCmd`, which means the bumped files land *inside* the same
# `chore(release):` commit that @semantic-release/git creates - and therefore
# inside the tag. The previous approach (a `sed` step after `npx
# semantic-release`) could only ever produce a follow-up commit, leaving the
# tagged tree still carrying the old version.
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

echo "set version to $VERSION"
