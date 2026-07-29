#!/usr/bin/env bash
# Hand the workflow the two facts the publish jobs gate on.
#
# The release step runs `npx semantic-release` as a plain shell command, which
# emits no step outputs of its own - `outputs.new-release-published` and
# friends only exist on the cycjimmy/semantic-release-action wrapper. Gating
# on them silently skipped the version-sync steps on every release since
# v1.0.0. This runs from `successCmd`, i.e. only once a release actually
# completed, and writes the outputs that step could not.
set -euo pipefail

VERSION="${1:?usage: record-release.sh <version>}"

# Absent when run outside Actions (a local `npx semantic-release --dry-run`),
# where there is no step to report to.
if [ -n "${GITHUB_OUTPUT:-}" ]; then
  {
    echo "published=true"
    echo "version=$VERSION"
  } >> "$GITHUB_OUTPUT"
fi

echo "released $VERSION"
