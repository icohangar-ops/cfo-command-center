#!/usr/bin/env bash
set -euo pipefail
WORKDIR="$(cd "$(dirname "$0")" && pwd)"
GIT=(git --git-dir="$WORKDIR/ccc.git" --work-tree="$WORKDIR")
: "${CODEBERG_PAT:?Set CODEBERG_PAT}"
: "${GITHUB_PAT:?Set GITHUB_PAT}"

CODEBERG_REPO="https://cubiczan:${CODEBERG_PAT}@codeberg.org/cubiczan/cfo-command-center.git"

# Recover deck HTML from overwritten remote (bash 3.2 safe — no mapfile).
while read -r sha _; do
  [[ -n "$sha" ]] || continue
  "${GIT[@]}" fetch "$CODEBERG_REPO" "$sha" 2>/dev/null || true
done < <("${GIT[@]}" ls-remote "$CODEBERG_REPO" 'refs/heads/*' 2>/dev/null || true)

for path in index.html cfo-command-center-deck.html; do
  found=0
  for sha in $("${GIT[@]}" rev-list --all 2>/dev/null | head -30); do
    if "${GIT[@]}" cat-file -e "${sha}:${path}" 2>/dev/null; then
      "${GIT[@]}" show "${sha}:${path}" >"$WORKDIR/$path"
      found=1
      break
    fi
  done
  if [[ "$found" -eq 0 ]]; then
    code=$(curl -sS -o "$WORKDIR/$path" -w '%{http_code}' \
      -H "Authorization: token ${CODEBERG_PAT}" \
      "https://codeberg.org/cubiczan/cfo-command-center/raw/branch/main/${path}" || echo 000)
    [[ "$code" == "200" && -s "$WORKDIR/$path" ]] || rm -f "$WORKDIR/$path"
  fi
done

if [[ ! -s "$WORKDIR/index.html" || ! -s "$WORKDIR/cfo-command-center-deck.html" ]]; then
  echo "error: could not recover deck HTML" >&2
  exit 1
fi

"${GIT[@]}" add index.html cfo-command-center-deck.html
if ! "${GIT[@]}" diff --cached --quiet; then
  "${GIT[@]}" commit -m "$(cat <<'EOF'
docs: add project presentation deck HTML

Restore deck files after codebase recovery.
EOF
)"
fi

exec "$WORKDIR/../push-both-remotes.sh" \
  git --git-dir="$WORKDIR/ccc.git" --work-tree="$WORKDIR" \
  cfo-command-center
