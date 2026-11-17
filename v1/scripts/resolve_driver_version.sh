#!/usr/bin/env bash
# Resolve the default "latest" policy to an actual published release tag.
# Explicit local DRIVER_VERSION overrides remain available for diagnosis.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
version="${DRIVER_VERSION:-$(cat "${ROOT}/scripts/driver-version")}"
if [ "${version}" != latest ]; then
  printf '%s\n' "${version}"
  exit 0
fi
repo="${DRIVER_GH_REPO:-redis/redis-adbc-driver}"
if command -v gh >/dev/null && gh auth status >/dev/null 2>&1; then
  gh api "repos/${repo}/releases/latest"
else
  curl -fsSL "https://api.github.com/repos/${repo}/releases/latest"
fi | python3 -c 'import json, sys; tag = json.load(sys.stdin)["tag_name"]; assert isinstance(tag, str) and tag.strip(), "Missing release tag"; print(tag)'
