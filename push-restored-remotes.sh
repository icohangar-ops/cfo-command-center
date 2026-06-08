#!/usr/bin/env bash
set -euo pipefail
WORKDIR="$(cd "$(dirname "$0")" && pwd)"
exec "$WORKDIR/../push-both-remotes.sh" \
  git --git-dir="$WORKDIR/ccc.git" --work-tree="$WORKDIR" \
  cfo-command-center --force
