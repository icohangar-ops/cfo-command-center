#!/usr/bin/env bash
# Check whether GitHub or Codeberg still has full cfo-command-center history.
set -euo pipefail
: "${CODEBERG_PAT:?Set CODEBERG_PAT}"
: "${GITHUB_PAT:?Set GITHUB_PAT}"

REPO=cfo-command-center
CB="https://cubiczan:${CODEBERG_PAT}@codeberg.org/cubiczan/${REPO}.git"
GH="https://x-access-token:${GITHUB_PAT}@github.com/Cubiczan/${REPO}.git"

probe() {
  local label="$1" url="$2"
  echo "=== $label ==="
  if ! git ls-remote "$url" HEAD 2>/dev/null; then
    echo "(remote missing or unreachable)"
    return 1
  fi
  local tmp
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  git clone --depth 20 --quiet "$url" "$tmp/repo"
  echo "root files:"
  ls -1 "$tmp/repo" | head -20
  echo "recent commits:"
  git -C "$tmp/repo" log --oneline -5
  echo
}

probe codeberg "$CB" || true
probe github "$GH" || true
