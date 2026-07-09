#!/usr/bin/env bash
# Compact multi-branch status for aipc-strix-halo (and similar repos).
# Prints a table agents can paste into a finish report.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "${ROOT}" ]]; then
  echo "not a git repo" >&2
  exit 1
fi
cd "$ROOT"

MAIN_REF="main"
if git show-ref --verify --quiet refs/heads/main; then
  MAIN_REF="main"
elif git show-ref --verify --quiet refs/heads/master; then
  MAIN_REF="master"
fi

# Best-effort fetch (non-fatal if offline)
git fetch origin --prune 2>/dev/null || true

CURRENT="$(git branch --show-current 2>/dev/null || echo DETACHED)"
DIRTY_N="$(git status --porcelain | wc -l | tr -d ' ')"
echo "repo: $ROOT"
echo "current: $CURRENT"
echo "main_ref: $MAIN_REF"
echo "dirty: ${DIRTY_N} path(s)"
if [[ "$DIRTY_N" != "0" ]]; then
  echo "dirty_paths:"
  git status --porcelain | head -30 | sed 's/^/  /'
  [[ "$DIRTY_N" -gt 30 ]] && echo "  … ($((DIRTY_N - 30)) more)"
fi
echo ""
printf '%-42s %-12s %-14s %-14s %s\n' "BRANCH" "TRACKING" "vs_main" "vs_origin" "NOTE"
printf '%-42s %-12s %-14s %-14s %s\n' "------------------------------------------" "------------" "--------------" "--------------" "----"

# Local branches only (skip remotes-only noise)
while IFS= read -r branch; do
  [[ -z "$branch" ]] && continue
  # skip worktree detached names if weird
  tracking="-"
  upstream="$(git rev-parse --abbrev-ref --symbolic-full-name "${branch}@{upstream}" 2>/dev/null || true)"
  if [[ -n "$upstream" ]]; then
    ahead="$(git rev-list --count "${upstream}..${branch}" 2>/dev/null || echo 0)"
    behind="$(git rev-list --count "${branch}..${upstream}" 2>/dev/null || echo 0)"
    tracking="A${ahead}/B${behind}"
  fi

  vs_main="-"
  if git show-ref --verify --quiet "refs/heads/${MAIN_REF}"; then
    ma="$(git rev-list --count "${MAIN_REF}..${branch}" 2>/dev/null || echo 0)"
    mb="$(git rev-list --count "${branch}..${MAIN_REF}" 2>/dev/null || echo 0)"
    vs_main="A${ma}/B${mb}"
  fi

  vs_origin="-"
  if git show-ref --verify --quiet "refs/remotes/origin/${branch}"; then
    oa="$(git rev-list --count "origin/${branch}..${branch}" 2>/dev/null || echo 0)"
    ob="$(git rev-list --count "${branch}..origin/${branch}" 2>/dev/null || echo 0)"
    vs_origin="A${oa}/B${ob}"
  elif git show-ref --verify --quiet "refs/remotes/origin/${MAIN_REF}" && [[ "$branch" == "$MAIN_REF" ]]; then
    oa="$(git rev-list --count "origin/${MAIN_REF}..${branch}" 2>/dev/null || echo 0)"
    ob="$(git rev-list --count "${branch}..origin/${MAIN_REF}" 2>/dev/null || echo 0)"
    vs_origin="A${oa}/B${ob}"
  fi

  note=""
  [[ "$branch" == "$CURRENT" ]] && note="*current"
  # Flag "ready to offer merge": has commits not in main, clean relative story
  if [[ "$vs_main" == A[1-9]* || "$vs_main" == A[1-9][0-9]* ]]; then
    if [[ "$note" == *current* ]]; then
      note="${note}, merge-candidate"
    else
      note="merge-candidate"
    fi
  fi

  printf '%-42s %-12s %-14s %-14s %s\n' "$branch" "$tracking" "$vs_main" "$vs_origin" "$note"
done < <(git for-each-ref --format='%(refname:short)' refs/heads/ | sort)

echo ""
echo "legend: A=ahead B=behind | vs_main = commits relative to ${MAIN_REF}"
echo "tip: merge-candidate = branch has commits not yet on ${MAIN_REF}"

# Optional PR hint
if command -v gh >/dev/null 2>&1; then
  echo ""
  echo "open PRs (gh):"
  gh pr list --limit 8 2>/dev/null || echo "  (gh unavailable or not authenticated)"
fi
