#!/usr/bin/env bash
# Search Zan-maker GitHub for a full cfo-command-center backup.
set -euo pipefail
: "${ZAN_MAKER_PAT:?Set ZAN_MAKER_PAT}"

ORG="${ZAN_MAKER_ORG:-Zan-maker}"
REPO="${CCC_REPO_NAME:-cfo-command-center}"
API="https://api.github.com"

gh_api() {
  curl -fsS -H "Authorization: token ${ZAN_MAKER_PAT}" \
    -H "Accept: application/vnd.github+json" "$@"
}

echo "=== repos on ${ORG} matching cfo/command ==="
gh_api "${API}/users/${ORG}/repos?per_page=100&type=all" | python3 -c "
import json, sys
repos = json.load(sys.stdin)
for r in sorted(repos, key=lambda x: x['name'].lower()):
    n = r['name'].lower()
    if 'cfo' in n or 'command' in n:
        print(f\"{r['full_name']}\tpushed={r.get('pushed_at','')}\tsize={r.get('size',0)}\")
print(f'--- scanned {len(repos)} public repos')
"

probe_clone() {
  local org="$1" repo="$2"
  echo
  echo "=== clone probe: ${org}/${repo} ==="
  local tmp url
  tmp="$(mktemp -d)"
  url="https://x-access-token:${ZAN_MAKER_PAT}@github.com/${org}/${repo}.git"
  if ! git ls-remote "$url" HEAD >/dev/null 2>&1; then
    echo "(missing or no access)"
    rm -rf "$tmp"
    return 1
  fi
  git clone --depth 30 --quiet "$url" "$tmp/repo"
  echo "root files:"
  ls -1 "$tmp/repo" | head -25
  echo "recent commits:"
  git -C "$tmp/repo" log --oneline -8
  local ok=0
  for marker in README.md pyproject.toml package.json src; do
    [[ -e "$tmp/repo/$marker" ]] && ok=1
  done
  if [[ "$ok" -eq 1 ]]; then
    echo "RESULT: FULL BACKUP — use CCC_BACKUP_ORG=${org} CCC_BACKUP_REPO=${repo}"
  else
    echo "RESULT: deck-only or sparse (not a full backup)"
  fi
  rm -rf "$tmp"
}

for candidate in "$REPO" CFO-Command-Center cfo_command_center; do
  probe_clone "$ORG" "$candidate" || true
done
