---
name: lieutenant
description: Use when an external agent (Qwen / GLM / sonnet / opus / any model in a 副官-role session) is about to execute a task spec file dispatched by 大哥. The skill encodes the repo's conventions (CLAUDE.md §0/§3/§5/§7/§8/§11), self-identification rules, the recurring failure modes (RED FLAGS) the agent must NOT reproduce, the build-time-vs-runtime split, the pre-commit verification gates, and the commit + log append + push protocol. The agent invokes this skill BEFORE reading the task spec, applies it AS guardrails throughout, and verifies AGAINST it before commit.
---

# 副官 (Lieutenant) — execute a dispatched task

You are reading this because 大哥 dispatched you a task. Your client may be Aider, Goose, Cline, Claude Code, Codex, or any other agent runtime. This skill is the **same playbook regardless of client**.

Follow phases 1-5 in order. Do not skip phase 1 — self-identification affects every commit you make.

## Phase 1 — Self-identify

Determine which model is executing you. This goes in the `Co-authored-by:` trailer per CLAUDE.md §11. Common identities:

- `claude-opus-4-7` / `claude-opus-4-8` — if you are Claude Opus
- `claude-sonnet-4-6` — if you are Claude Sonnet 4.6
- `claude-haiku-4-5` — Claude Haiku 4.5
- `Qwen3.7-max` — Qwen 3 series
- `GLM5.2` — Zhipu GLM
- `gpt-5-coding` / similar — OpenAI

If you cannot self-identify with certainty, ask the user. Do NOT guess in the trailer — wrong attribution corrupts the audit log (`docs/agent-log.md`) which 大哥 relies on for retrospective review.

Also note the **Agent-Orchestrator**: who dispatched you. The dispatch prompt typically includes this (default `claude-opus-4-7` for opus 大哥 sessions). If not stated, ask.

## Phase 2 — Read context

Your client does NOT carry conversation history from 大哥. Read these files before doing ANYTHING:

1. `/Users/birdyo/forfun/aipc_setup/CLAUDE.md` — full file. §0 (roles), §3 (module discipline), §5 (secrets — never bake), §7 (LiteLLM contract), §8 (style), §11 (commit trailers) are non-negotiable.
2. The task spec file the user pointed you at (typically `/tmp/<role>-q<N>-<slug>.md`). Read it end-to-end before starting any edit.
3. Any file the task spec's "Read FIRST" section names.
4. `tools/aipc_lib/modules.py` if your task touches modules — confirm the `.disabled` skip semantics.

If the task spec says "see prior conversation for context" — STOP and ask the user. You have no prior conversation. The dispatch must be self-contained.

## Phase 3 — Internalize the RED FLAGS

These are the failure patterns prior 副官 runs have repeatedly made. Do NOT add them. Scan your own diff for them before committing.

### 🔴 In `post-install.sh` (runs at IMAGE BUILD time, no init, no network, no services):

- ❌ `systemctl --now <service>` — `--now` starts the service. No init runs at build. Use plain `systemctl enable` if you must enable a unit; let runtime start it.
- ❌ `nc -z localhost <port>` / `nc -z 127.0.0.1 <port>` — nothing listens at build.
- ❌ `curl http://localhost/...` / `curl http://127.0.0.1/...` — same reason.
- ❌ `psql -c ...`, `redis-cli ...`, `mongo ...` — any DB client call. No DB at build.
- ❌ `pip install` / `npm install -g` / `cargo install` — use `rpm-ostree install` from a repo already in place, or document distrobox-side runtime install.
- ❌ Writing decrypted secrets — age key is not on the build host (CLAUDE.md §5).
- ❌ `modprobe` / `udevadm` — no kernel running, no udev at build.

### 🔴 In `files/` paths:

- ❌ `files/usr/local/...` — on bootc, `/usr/local` is a symlink to `/var/usrlocal` which is NOT writable at build. Relocate to `/usr/lib/...` or `/usr/bin/...`. This pattern bit `secrets-sops` (fixed in 503c175) and `db-postgres` (cf886a1).

### 🔴 In any file in your diff:

- ❌ Plaintext secrets. Token shapes to grep for: `sk-ant-`, `sk-proj-`, `sk-[a-zA-Z0-9]{20,}`, `ghp_`, `xoxb-`, `AKIA[A-Z0-9]{16}`, `eyJ[a-zA-Z0-9_-]{20,}` (JWT-ish).
- ❌ Hardcoded AI-tool vendor endpoints (api.openai.com, api.anthropic.com, generativelanguage.googleapis.com). All AI tools MUST point at the LiteLLM gateway `http://127.0.0.1:4000`. Direct vendor calls are allowed only inside `modules/llm-*/` itself.
- ❌ `sed` operations on `docs/agent-log.md`. Two prior runs (1d36edb, ae40146) corrupted historic rows that way. Use `python -m aipc_lib.cli log append` (added by 201e72b).

### Correct build-time vs runtime split

| Concern | Where it goes |
|---|---|
| COPY a file into the image | `post-install.sh` (build time) |
| `systemctl enable` a unit (no --now) | `post-install.sh` (build time) |
| `rpm-ostree install` from a repo already baked | `post-install.sh` (build time) |
| Start a service | systemd unit + boot (runtime) |
| Wait for a port / hit an API | systemd unit `ExecStart` script (runtime) |
| Decrypt secrets via SOPS | systemd oneshot with `ConditionPathExists=/etc/aipc/age.key` (runtime). See `modules/secrets-sops/files/etc/systemd/system/aipc-decrypt-cloud-keys.service` for the canonical pattern. |
| DB schema init / first-time bootstrap | systemd oneshot, `Type=oneshot`, `RemainAfterExit=yes`, sentinel file `ConditionPathExists=!/var/lib/<name>/.initialized` so it only runs once |

When in doubt: would this work on a machine with no network, no /etc/aipc/age.key, no service running? If no → it belongs in a systemd unit, not `post-install.sh`.

## Phase 4 — Execute the task

Follow the task spec exactly. Do not invent files, modules, or scope. The dispatch is intentionally precise because you (the 副官) have no broader context.

If the task spec is ambiguous about a specific decision: pick the option closer to the task spec's intent and add a `# ponytail:` comment naming the assumption. Do NOT invent a whole new module or skip a requirement.

Constraints that apply to every dispatched task:

- DO NOT remove `.disabled` from a module unless the task explicitly says so. Enablement is hardware-verified work, not 副官 scope.
- DO NOT modify `openspec/changes/<spec>/` unless the task names the spec as the target. Spec changes are 大哥 work.
- DO NOT modify `CLAUDE.md` unless the task explicitly says so.
- DO NOT touch modules outside the task's scope.

## Phase 5 — Pre-commit verification

Run ALL of these. If any fails, fix the underlying issue (not the check). Do NOT commit with a known failure.

### 5.1 — Tests

```sh
cd /Users/birdyo/forfun/aipc_setup/tools && python -m pytest -q
```

Pass count should be at or above the prior baseline. No new failures, no skips you didn't intend.

### 5.2 — Render

```sh
cd /Users/birdyo/forfun/aipc_setup && \
  python -m aipc_lib.cli render bootc \
    --image-ref test --build-date "$(date -u +%Y-%m-%d)" \
    --out /tmp/cf-test
```

Must exit 0. The generated `/tmp/cf-test` should NOT reference any `.disabled` module.

### 5.3 — OpenSpec validation

For each OpenSpec change touched (or referenced by the task):

```sh
openspec validate <change-name> --strict
```

Must return `Change '<name>' is valid`.

### 5.4 — RED FLAG self-scan

```sh
# Build-time / runtime confusion in new or modified post-install scripts:
grep -nE "^[^#]*(systemctl.*--now|nc -z|psql -c|curl http://(localhost|127))" \
  modules/*/post-install.sh

# /usr/local trap:
find modules -type d -path "*/files/usr/local"

# Plaintext-looking secrets in your diff:
git diff --cached | grep -nE "sk-ant-[a-zA-Z0-9]{8,}|sk-proj-|sk-[a-zA-Z0-9]{30,}|ghp_[a-zA-Z0-9]{20,}|AKIA[A-Z0-9]{16}|xoxb-"
```

All three should produce only known-pre-existing offenders (Phase 1 LLM modules, db-postgres if you didn't fix it) — never your own new lines. If your diff added a hit, fix it.

### 5.5 — shellcheck

```sh
shellcheck modules/*/post-install.sh modules/*/verify.sh
```

Should exit 0 for files you changed.

### 5.6 — Architectural self-check

Ask yourself, before committing:

- Does anything I wrote depend on a service running, a network call succeeding, or a secret being decrypted at IMAGE BUILD TIME? If yes — split to runtime.
- Did I shipping anything to `files/usr/local/...`? If yes — relocate to `/usr/lib/` or `/usr/bin/`.
- Did I change anything outside the task scope? If yes — revert. File a separate dispatch if it matters.
- Is every new shell script idempotent (safe to re-run)? If no — make it so.

## Phase 6 — Commit + push

### 6.1 — Append the agent-log row

Use the `aipc log append` subcommand (added in commit 201e72b precisely to prevent sed-style corruption of historic rows):

```sh
cd /Users/birdyo/forfun/aipc_setup && \
  python -m aipc_lib.cli log append \
    --date "$(date -u +%Y-%m-%d)" \
    --role 副官 \
    --model "<your-model-id-from-phase-1>" \
    --run-label "<run-label-from-task-spec>" \
    --spec-task "<spec-task-from-task-spec>" \
    --sha-range "(this commit)" \
    --outcome "<one-line summary of what this commit does and what verification ran>"
```

Do NOT use `sed`, `echo >>`, or any other write to `docs/agent-log.md`. Only `aipc log append`.

### 6.2 — Stage and commit

Stage all relevant changes:

```sh
git add <specific-paths>
```

Avoid `git add -A` / `git add .` — too easy to commit unrelated dirty files. Add by path.

Commit with the trailer per CLAUDE.md §11:

```
<type>(<scope>): <short title>

<body explaining WHY, not WHAT — the diff shows WHAT>

Co-authored-by: <your-model-id> <noreply@anthropic.com>
Agent-Role: 副官
Agent-Run: <run-label>
Spec-Task: <spec-task>
Agent-Orchestrator: <orchestrator-id, usually claude-opus-4-7>
```

If you (the worker) and the orchestrator are the same model in the same session, omit `Agent-Orchestrator:` per CLAUDE.md §11.

### 6.3 — Push

```sh
git push origin main
```

If your client's policy classifier blocks the push (warning about bypass-PR-review or similar): do NOT retry, do NOT force. Stop and tell the user "push blocked by classifier; commits sitting locally as <sha-list>." 大哥 will approve or reroute.

### 6.4 — Report back to 大哥

Single completion message with:

- commit sha (and the log-fix sha if you needed a second commit)
- files changed / created / deleted (rough counts)
- pytest pass count
- render exit code (should be 0)
- `openspec validate` results (one line per change)
- RED FLAG self-scan results (number of hits, ideally 0 in your diff)
- shellcheck result (should be 0 exit)
- one-line summary of what the commit accomplished

## When to STOP and ask, not press on

- The task spec contradicts itself, or contradicts CLAUDE.md.
- The task spec asks you to modify a spec you don't have authority to (`openspec/changes/...` outside the task target).
- Phase 5 verification fails and the fix is outside your task scope (e.g., the pre-existing pytest is already red).
- A RED FLAG is required to complete the task as written (means the task spec is wrong — 大哥 needs to re-spec).
- Push is blocked.
- Self-identification is uncertain.

In all these cases: leave the work uncommitted, report to user, wait for direction.

## Anti-patterns specific to 副官 work

- ❌ Inventing modules not named in the task spec.
- ❌ "Improving" things outside scope (cleanup commits, rename refactors). One task = one commit.
- ❌ Skipping verification because "the task is small."
- ❌ Reaching for `sed` on `docs/agent-log.md`. There's a tool. Use it.
- ❌ Committing with a vague subject line. Use `<type>(<scope>): <verb-led title>`.
- ❌ `git push --force` — never, on this repo.
- ❌ `git commit --amend` after push — never. New commit forward-fixes the prior.
- ❌ Acting on prior conversation context you don't have. The task spec is your whole world.
