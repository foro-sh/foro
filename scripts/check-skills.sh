#!/usr/bin/env bash
# Staleness gate for the plugin trees. Skills and plugin manifests get copied
# into agents' contexts and into other repos, so a stale sentence here ships
# everywhere they go.
set -uo pipefail
cd "$(dirname "$0")/.."

status=0

# foro.yaml was replaced by pyproject.toml / package.json, and a mention of it
# sends an agent to write a file the platform no longer reads.
if grep -rn 'foro\.yaml' plugins/; then
  echo "::error::plugins/ mentions foro.yaml, which no longer exists - project config lives in pyproject.toml or package.json"
  status=1
fi

# Agents pick a skill by its frontmatter, so a SKILL.md without it is never
# selected. The block has to open the file and be closed.
for skill in plugins/*/skills/*/SKILL.md; do
  if ! frontmatter=$(awk 'NR==1 { if ($0 != "---") exit 1; next }
                          $0 == "---" { closed = 1; exit }
                          { print }
                          END { if (!closed) exit 1 }' "$skill"); then
    echo "::error file=$skill::no frontmatter block (--- ... ---) at the top of the file"
    status=1
    continue
  fi
  for key in name description; do
    if ! grep -q "^$key: *[^ ]" <<<"$frontmatter"; then
      echo "::error file=$skill::frontmatter has no '$key'"
      status=1
    fi
  done
done

exit $status
