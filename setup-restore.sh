#!/usr/bin/env bash
# Restore cfo-command-center from local dir or a GitHub backup org (e.g. Zan-maker).
set -euo pipefail
WORKDIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE="${CCC_SOURCE:-}"
GIT_DIR="$WORKDIR/ccc.git"
GIT=(git --git-dir="$GIT_DIR" --work-tree="$WORKDIR")

looks_like_project() {
  local dir="$1"
  [[ -f "$dir/README.md" || -f "$dir/pyproject.toml" || -f "$dir/package.json" || -d "$dir/src" ]]
}

clone_backup() {
  local org="$1" repo="$2" pat="$3" dest="$4"
  local url="https://x-access-token:${pat}@github.com/${org}/${repo}.git"
  rm -rf "$dest"
  git clone --quiet "$url" "$dest"
}

if [[ -z "$SOURCE" ]]; then
  BACKUP_ORG="${CCC_BACKUP_ORG:-Zan-maker}"
  BACKUP_REPO="${CCC_BACKUP_REPO:-cfo-command-center}"
  BACKUP_PAT="${CCC_BACKUP_PAT:-${ZAN_MAKER_PAT:-${GITHUB_PAT:-}}}"
  if [[ -z "$BACKUP_PAT" ]]; then
    echo "error: set CCC_SOURCE, ZAN_MAKER_PAT, or GITHUB_PAT" >&2
    exit 1
  fi

  SOURCE="$WORKDIR/_github-mirror"
  tried=()
  for org in "$BACKUP_ORG" Cubiczan; do
    for repo in "$BACKUP_REPO" CFO-Command-Center; do
      tried+=("${org}/${repo}")
      if clone_backup "$org" "$repo" "$BACKUP_PAT" "$SOURCE" 2>/dev/null && looks_like_project "$SOURCE"; then
        echo "backup: ${org}/${repo}"
        break 2
      fi
      rm -rf "$SOURCE"
    done
  done

  if ! looks_like_project "$SOURCE"; then
    echo "error: no full backup found (tried: ${tried[*]})" >&2
    echo "Run ./probe-zan-maker.sh or set CCC_SOURCE=/path/to/backup" >&2
    exit 1
  fi
fi

if ! looks_like_project "$SOURCE"; then
  echo "error: $SOURCE does not look like a full project backup" >&2
  exit 1
fi

rsync -a --delete --exclude='__pycache__' --exclude='.DS_Store' --exclude='.git' \
  --exclude='ccc.git' --exclude='*.sh' --exclude='_github-mirror' \
  "$SOURCE/" "$WORKDIR/"

grep -q '^ccc\.git/$' "$WORKDIR/.gitignore" 2>/dev/null || echo "ccc.git/" >> "$WORKDIR/.gitignore"

rm -rf "$GIT_DIR" "$WORKDIR/.git"
GIT_TEMPLATE_DIR= git -c init.template= init --separate-git-dir="$GIT_DIR" "$WORKDIR"
echo "gitdir: ccc.git" > "$WORKDIR/.git"

"${GIT[@]}" config user.name "Shyam Desigan"
"${GIT[@]}" config user.email "shyamdesigan@gmail.com"
"${GIT[@]}" checkout -B main
"${GIT[@]}" add -A
"${GIT[@]}" commit -m "$(cat <<'EOF'
restore: recover CFO Command Center after deck overwrite

Restored full project from backup after remote was reduced to
presentation-deck HTML only.
EOF
)"
echo "Commit: $("${GIT[@]}" rev-parse HEAD)"
echo "Next: export CODEBERG_PAT GITHUB_PAT && ./push-restored-remotes.sh"
