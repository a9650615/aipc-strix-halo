#!/usr/bin/env bash
# Remove known *process residue* only. Never git-restore source edits.
# Usage: clean-process.sh [--dry-run]
set -euo pipefail

DRY=0
[[ "${1:-}" == "--dry-run" ]] && DRY=1

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "${ROOT}" ]]; then
  echo "not a git repo" >&2
  exit 1
fi
cd "$ROOT"

run() {
  if [[ "$DRY" -eq 1 ]]; then
    echo "DRY: $*"
  else
    eval "$@"
  fi
}

echo "clean-process: root=$ROOT dry_run=$DRY"

# 1) Python / test caches inside repo (skip .git)
# Avoid deleting across huge unrelated trees slowly: limit depth on find.
while IFS= read -r -d '' d; do
  run "rm -rf $(printf '%q' "$d")"
done < <(find . -path './.git' -prune -o -path './.claude/worktrees' -prune -o \
  -type d \( -name '__pycache__' -o -name '.pytest_cache' -o -name '.ruff_cache' -o -name '*.egg-info' \) \
  -print0 2>/dev/null)

while IFS= read -r -d '' f; do
  run "rm -f $(printf '%q' "$f")"
done < <(find . -path './.git' -prune -o -path './.claude/worktrees' -prune -o \
  -type f \( -name '*.py[cod]' -o -name '*.orig' -o -name '*.rej' -o -name '*~' -o -name '*.swp' -o -name '.DS_Store' \) \
  -print0 2>/dev/null)

# 2) Conflict marker scan (report only)
MARKER=$(printf '%s%s' '<<<' '<<<< ')
if git grep -nF "$MARKER" -- . ':(exclude).claude/skills/branch-status-merge/**' ':(exclude)docs/agent-log.md' 2>/dev/null | head -5 | grep -q .; then
  echo "WARN: possible conflict markers still in tree:" >&2
  git grep -nF "$MARKER" -- . ':(exclude).claude/skills/branch-status-merge/**' ':(exclude)docs/agent-log.md' 2>/dev/null | head -10 || true
fi

# 3) Summarize remaining porcelain
echo ""
echo "remaining git status:"
if git status --porcelain | grep -q .; then
  git status --porcelain | head -40
  count="$(git status --porcelain | wc -l | tr -d ' ')"
  echo "(${count} path(s) — classify as deliverable / unrelated WIP / accidental)"
  exit 2
else
  echo "(clean)"
  exit 0
fi
