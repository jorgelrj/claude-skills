#!/usr/bin/env bash
# Tag every plugin at the version its plugin.json declares: <plugin>-v<version>.
# Idempotent: a tag that already exists is left alone. A tag that exists on a
# different commit than HEAD is fine (the version was released earlier).
#
# Usage: scripts/tag-plugin-versions.sh [--push]
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
push=0
[[ "${1:-}" == "--push" ]] && push=1

created=()
for manifest in plugins/*/.claude-plugin/plugin.json; do
  read -r name version < <(python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); print(m["name"], m["version"])' "$manifest")
  tag="${name}-v${version}"
  if git rev-parse -q --verify "refs/tags/${tag}" >/dev/null; then
    echo "EXISTS ${tag}"
    continue
  fi
  git tag -a "${tag}" -m "${name} ${version}"
  echo "TAGGED ${tag} at $(git rev-parse --short HEAD)"
  created+=("${tag}")
done

if (( push )) && (( ${#created[@]} )); then
  git push origin "${created[@]/#/refs/tags/}"
fi
