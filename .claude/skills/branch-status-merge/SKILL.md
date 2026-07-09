---
name: branch-status-merge
description: >
  After finishing work (or when asked about branch/merge status), proactively
  audit local + remote git branch state, scrub process residue so the tree is
  not left dirty, report merge-candidates, and ASK whether to merge back to
  main — never auto-merge. Use when: task complete, commit done, "合併",
  "merge back", "分支狀態", "要不要合回 main", "清乾淨", "dirty", session
  wrap-up, /branch-status-merge, /finish-merge-check. Also use at end of
  lieutenant dispatches that produced commits.
---

# Branch status + clean tree + ask-to-merge

You are finishing work or the user asked about branch hygiene.

**Hard rules:**

1. **Do not silently merge** to `main`.
2. **Do not leave a dirty process trail** after “done” — no untracked junk,
   no accidental WIP mixed into finish, no half-stashed mess without telling
   the user.
3. Query real `git` state; do not invent branch status.

## When this skill MUST fire

Run automatically when any of:

1. You just **committed** (or user said 做完了 / done).
2. Session wrap-up after non-trivial code changes.
3. User asks merge / 合併 / branch status / 合回 main / 清乾淨 / dirty.
4. A 副官/執行兵 dispatch reports completion with SHAs.

## Definition: “乾淨” (clean enough to claim done)

| Allowed after finish | **Not** allowed (process residue) |
|----------------------|-----------------------------------|
| Intentional WIP the user still wants (listed explicitly) | `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.ruff_cache/` |
| Nothing else | `*.orig`, `*.rej`, `*~`, `*.swp`, editor backup files |
| | Untracked temp scripts/logs you created under `/tmp` for this task (delete when done) |
| | Staged secrets / accidental `git add` of generated renders |
| | Unrelated module edits you touched “while there” and never decided commit vs revert |
| | Untracked skill/scaffold dirs you duplicated and abandoned |
| | Merge conflict markers left in files |
| | Stash created for merge that was never popped **and** never mentioned |

**Claiming “done” with a dirty worktree full of your process files is a failure.**

## Phase 0 — Scrub process residue (before status report)

From repo root:

```bash
bash .claude/skills/branch-status-merge/scripts/clean-process.sh
# or:
bash .claude/skills/branch-status-merge/scripts/clean-process.sh --dry-run
```

The cleaner **may auto-delete only known residue** (pycache, pytest/ruff caches,
`*.orig`/`*.rej`/`*~` inside the repo). It **must not** `git restore` or delete
real source edits.

Then classify remaining `git status --porcelain` lines:

| Class | Action |
|-------|--------|
| **A — task deliverable** not yet committed | Commit (proper trailers) or ask user |
| **B — unrelated WIP** (other modules/docs) | Leave listed; do **not** fold into your commit; do **not** pretend tree is clean |
| **C — accidental touch** | `git restore` / `git clean` **only** for files you know you dirtied by mistake |
| **D — should be gitignored** | Add to `.gitignore` in a focused commit if pattern is recurring |

If Class B remains, say so plainly:

> Worktree still dirty with N unrelated paths (list). Your task commits are clean; leftover is pre-existing / other WIP.

Never “stash and forget” Class B without naming the stash in the finish report.

## Phase 1 — Query branches

```bash
bash .claude/skills/branch-status-merge/scripts/branch-status.sh
```

Fallback:

```bash
git fetch origin --prune 2>/dev/null || true
git status -sb
git branch -vv
git log --oneline main..HEAD 2>/dev/null | head -20
git log --oneline HEAD..main 2>/dev/null | head -10
git stash list | head -5
```

Ignore deep worktree agent branches unless user is in one — still note if they are merge-candidates.

## Phase 2 — Report

```markdown
### Cleanliness
- Process residue: cleaned / none / dry-run listed
- Remaining dirty: <none | N paths (class B: …)>

### Branch status
| Branch | vs main | vs origin | Dirty? | Note |
|--------|---------|-----------|--------|------|
| … | A/B | A/B | … | *current*, merge-candidate |

### Not in main yet
- abc1234 …
```

## Phase 3 — Ask (mandatory)

Options:

1. **Merge into main now** (only if tree is Class-A-clean or Class B stashed **with user OK**)
2. **Push branch only**
3. **Do nothing** (leave unintegrated; still require cleanliness report)
4. **Other** (cherry-pick / selective)

Recommend based on:

| Situation | Recommend |
|-----------|-----------|
| Ahead of main, tests green, tree clean | (1) |
| Class B dirty | (2) or stash Class B with name, then (1) after ask |
| Behind main | merge/rebase main first, re-ask |
| On main, unpushed | push main (ask) |

**Never** force-push `main`. **Never** merge without yes **this turn**.

## Phase 4 — If user says merge

1. Re-run cleanliness: if dirty Class B → stash with  
   `git stash push -u -m "wip-pre-merge-<date>" -- <paths>` **or** stop and ask.
2. `git fetch origin`
3. `git checkout main && git pull --ff-only origin main`
4. `git merge <feature-branch>`
5. Conflicts:
   - `docs/agent-log.md`: keep **union** / fuller log; never drop rows.
   - Code: resolve properly; re-test if non-trivial.
6. `git push origin main` after success (when user wanted 合併回去).
7. Push feature tip if useful.
8. Return to prior branch; `git stash pop` only if user still wants that WIP; else leave stash **named and reported**.
9. Final cleanliness check: `git status --porcelain` should be empty **or** only reported Class B.

Trailers on merge commit (CLAUDE.md §11):

```
Co-authored-by: <model-id> <noreply@…>
Agent-Role: 大哥 | 副官
Agent-Run: merge-<branch>-to-main-<date>
```

Agent-log: `python -m aipc_lib.cli log append` only — no `sed` on `docs/agent-log.md`.

## Phase 5 — If user declines merge

- OK; still must have scrubbed process residue.
- One-line reminder: branch still A ahead of main.
- No nag until new commit or re-ask.

## Anti-patterns

- ❌ Auto-merge
- ❌ “Done” with `__pycache__`, conflict markers, or mystery untracked dirs
- ❌ Stashing unrelated WIP without telling the user the stash name
- ❌ Committing `/tmp` scripts, generated `Containerfile.generated`, secrets
- ❌ Force-push / `reset --hard` to hide dirt
- ❌ Only checking current branch, ignoring other local merge-candidates

## Finish template

```
Done: <sha(s)>.
Clean: process residue removed; remaining dirty = <none | list>.
Branch: <current> A/B vs main.
Merge to main now? [yes / push-only / no]
```
