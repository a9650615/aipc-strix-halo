---
name: dispatch-qwen-task
description: Use when 大哥 needs to (1) review Qwen 副官's prior work, (2) write a new bounded task spec, and (3) give the user a one-line dispatch prompt to paste into Qwen's external client (Aider/Goose/Cline/web UI). The skill encodes the repo's conventions (CLAUDE.md §0/§5/§7/§8/§11), the recurring Qwen failure modes (RED FLAGS), the scaffold layout, the verification + commit + push pattern, and the agent-log append pattern.
---

# Dispatch a Qwen 副官 task

Use this skill any time the user says "派 Qwen", "派 副官", "寫 task for Qwen", "幫我寫 prompt 給 Qwen", or references this skill. The flow has **three phases — do them in order, do not skip phase 1**.

## Phase 1 — Review (audit Qwen's prior work)

Before writing any new task, audit what Qwen did since the last 大哥 review. This catches recurring failures before they compound.

### Step 1.1 — Walk recent commits

```sh
git --no-pager log --oneline -10
```

Identify commits authored by Qwen (look at `Co-authored-by: Qwen3.7-max` trailer). For each Qwen commit since the last 大哥 review:

```sh
git --no-pager show --stat <sha> | head -80
```

### Step 1.2 — Run the audit checklist

For every Qwen commit:

| # | Check | Command |
|---|---|---|
| 1 | All new modules have `.disabled` | `find modules -name ".disabled" \| sort` — every newly-scaffolded module must appear |
| 2 | No `systemctl --now`, `nc -z`, `curl localhost`, `psql -c` in any new post-install.sh | `grep -l "systemctl.*--now\\|nc -z\\|psql -c\\|curl http://localhost" modules/*/post-install.sh` |
| 3 | No `files/usr/local/*` paths (bootc /usr/local symlink trap) | `find modules -type d -path "*/files/usr/local"` — must be empty |
| 4 | No plaintext secrets in diff | grep diff for known secret shapes: `sk-ant-`, `sk-`, `ghp_`, `xoxb-`, `AKIA`, raw API key patterns |
| 5 | All AI tool configs point at LiteLLM (`http://127.0.0.1:4000`), not vendor endpoints | `grep -rE "(api_base\|api.openai.com\|api.anthropic.com)" modules/<new>/` |
| 6 | Trailer present and includes `Agent-Orchestrator: <opus session id>` | `git log --format=%B <sha>` |
| 7 | agent-log row appended (not sed-corrupted) | `git --no-pager show <sha> -- docs/agent-log.md` |
| 8 | OpenSpec validation still passes | `openspec validate <change-name> --strict` |

### Step 1.3 — Report findings to the user

Present concisely (mirror the Phase 6 / Phase 2 review I gave on commit cb2c7ea / cf886a1):

```
## 審核 N 件 Qwen 交件

| Commit | 評 |
|---|---|
| <sha1> <subject> | ✅ clean / ⚠️ 1 issue / 🔴 N bugs |
```

For each ⚠️/🔴 row, list specific issues with file paths and line numbers. State whether the bug ships (modules without `.disabled`) or is latent (will bite when `.disabled` removed).

**Do NOT proceed to Phase 2 if a 🔴 has shipped — write a forward-fix dispatch first.**

## Phase 2 — Write the task spec file

### File location and naming

`/tmp/qwen-<id>-<slug>.md`

- `<id>` = next sequential `qN` after the last existing `/tmp/qwen-q*.md`.
- `<slug>` = kebab-case short summary (`phase-6-scaffold`, `log-append-helper`, `db-postgres-fix`).

### Required sections (in order — paste these verbatim or close to it)

#### 1. Role line

```
You are 副官 (Qwen, Lieutenant role) at /Users/birdyo/forfun/aipc_setup.
```

#### 2. Precondition check (if applicable)

If this task depends on a prior Qwen commit landing:

```
**Precondition:** Q<N> (`<verifiable artifact>`) merged. Verify: `<one-line check command>`. If not, STOP.
```

#### 3. 🔴 RED FLAGS block (mandatory — never skip)

Always paste this block verbatim:

```
# 🔴 RED FLAG WARNING — READ FIRST

**Do NOT in post-install.sh (which runs at IMAGE BUILD time):**
- ❌ `systemctl --now <service>` — `--now` starts the service; no init runs at build.
- ❌ `nc -z localhost <port>` / `curl http://localhost/...` — nothing listens at build.
- ❌ `psql -c ...`, `redis-cli ...`, any client call to a service — same reason.
- ❌ `pip install` / `npm install -g` — use rpm-ostree from a baked repo, or document distrobox-side install.
- ❌ Writing decrypted secrets — age key not present at build (CLAUDE.md §5).

**Do NOT in files/:**
- ❌ Path `files/usr/local/...` — on bootc, /usr/local is a symlink to /var/usrlocal which is NOT writable at build. Relocate to /usr/lib/ or /usr/bin/. Bit secrets-sops (fixed in 503c175) and db-postgres in cf886a1.

**Build-time vs runtime split (correct patterns):**
- post-install.sh = build time. Use for: COPY-style file installs, `systemctl enable` (NO --now), `rpm-ostree install` from a repo already in place, idempotent file mode changes.
- systemd units = runtime. Use for: starting services, network calls, secret decryption (see modules/secrets-sops/files/etc/systemd/system/aipc-decrypt-cloud-keys.service for the ConditionPathExists pattern).
```

#### 4. Read FIRST list

Tell Qwen what to read before doing anything. Always:
- `CLAUDE.md` — list relevant sections: §0 roles, §3 module discipline, §5 secrets, §7 LiteLLM contract, §8 style, §11 trailers
- Relevant OpenSpec change dir (all 4 artifacts)
- A reference module known clean: usually `modules/system-base/` or `modules/secrets-sops/`
- `tools/aipc_lib/modules.py` if `.disabled` skip matters

#### 5. Task definition (precise)

- Exact list of files / modules to create — no ambiguity.
- Exact module names, bulleted. Qwen invents close-but-wrong names if vague.
- Standard per-module layout: `.disabled`, README.md, packages.txt, post-install.sh, verify.sh, plus optional `files/`, `env/`, `quadlet/`.

#### 6. Per-module specifics

Short paragraph per module: packages, files shipped, README cross-ref to a specific design decision (e.g., "documents D2"), runtime location (e.g., "runs in node distrobox").

#### 7. verify.sh shape (paste verbatim)

```sh
#!/bin/sh
set -eu
this_dir="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$this_dir/.disabled" ]; then
    echo "$(basename "$this_dir"): disabled (optional)" >&2
    exit 2
fi
exit 0
```

#### 8. Verification steps

Numbered checklist Qwen must run before committing:

1. `cd tools && python -m pytest -q` — green
2. `aipc render bootc --image-ref test --build-date <today> --out /tmp/cf-test` — succeeds
3. `grep -c "modules/<prefix>-" /tmp/cf-test` — must be 0 (modules `.disabled`, must not render)
4. `openspec validate <change-name> --strict` — passes
5. Scan all new post-install.sh for the 4 RED FLAG patterns — none allowed.

#### 9. Commit + push block (paste verbatim)

```
feat(<scope>): <title>

<body>

Co-authored-by: Qwen3.7-max <noreply@anthropic.com>
Agent-Role: 副官
Agent-Run: <run-label>-<YYYY-MM-DD>
Spec-Task: <change>#<task-ids>
Agent-Orchestrator: claude-opus-4-7
```

Plus: **use `aipc log append` for the agent-log row, NEVER sed**. (Added in commit 201e72b precisely to prevent the sed corruption that bit two prior runs.)

#### 10. Constraints reminder

Bulleted "DO NOT":
- DO NOT remove `.disabled` from any module — that's enablement, not scaffolding.
- DO NOT modify `openspec/` directories.
- DO NOT touch unrelated modules.
- DO NOT use sed on docs/agent-log.md.
- §5: zero plaintext secrets in the diff.
- §7: every LLM-bound call points at `http://127.0.0.1:4000` (LiteLLM), not vendor endpoints.
- §8: terse code, no useless comments. README is for "why".
- §11: trailer mandatory.

#### 11. Report-back ask

Specify what Qwen should return:
- commit sha
- file count (rough)
- pytest pass count
- render exit code
- grep result = 0
- confirmation that RED FLAG scan was clean

## Phase 3 — Give the user a simple dispatch prompt

After writing the spec file, give the user **a short copy-paste line** they paste into their Qwen client (Aider / Goose / Cline / web UI). The line tells Qwen to read the spec file and execute it.

Format (zh-TW, since user works in Chinese):

```
副官，請完整讀取 /tmp/qwen-<id>-<slug>.md 並執行其中所有指令。完成後回報 commit sha、檔案數、pytest 結果、render exit code、RED FLAG 掃描結果。
```

If you wrote multiple spec files in this turn, give a numbered list with dependency hints:

```
請依序餵 Qwen（彼此無依賴可同時，但 build push 會 race）：

1. 副官，請讀取 /tmp/qwen-q3-phase4-scaffold.md 並完整執行。
2. 副官，請讀取 /tmp/qwen-q4-phase3-scaffold.md 並完整執行。
3. ...
```

The dispatch line is intentionally **short** — it should be 1-2 sentences, no nested instructions. The complexity lives in the spec file.

## After Qwen commits (next session's Phase 1)

When the user reports a Qwen commit landed, START at Phase 1 (review). Do not skip to Phase 2 of the next task without auditing the last one first.

## Anti-patterns when generating the spec

- ❌ Skipping the Read FIRST list — Qwen has zero conversation context.
- ❌ Skipping RED FLAGS even if "the task is simple."
- ❌ Mixing multiple unrelated changes in one spec file — split into separate qN files.
- ❌ Omitting `Agent-Orchestrator: claude-opus-4-7` from the trailer template.
- ❌ Saying "do something reasonable" — Qwen invents things. Spec exact files.
- ❌ Saying "see prior conversation for context" — Qwen has none.
- ❌ Mixing Chinese and English in the spec body inconsistently — pick English for the spec (cleaner for Qwen's training distribution), Chinese for the user-facing dispatch line.

## When NOT to use this skill

- Trivial work Claude can do directly with its own tools — don't dispatch.
- Design judgment / spec drafting — 大哥 (or user) work, not 副官.
- Spec or CLAUDE.md changes — Qwen has repeatedly missed the bigger picture.
- Hardware verification — Qwen can't see the AI PC.
- Anything where the "right answer" depends on conversation context Claude has but Qwen doesn't.
