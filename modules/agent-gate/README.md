# agent-gate

Permission gate for risky agent actions (design.md D4/D5, tasks.md group 5:
5.1, 5.2, 5.4, 5.5). Grant/revoke/check/audit for time-bounded (`session`)
or task-bounded (`task`) authorisation of actions like `screen-control`,
`git-push`, `file-delete`, `email-send`. Every gated action (e.g.
`agent-tools-files`'s out-of-workspace `delete`) calls `check` before
proceeding; fails closed if the gate is unreachable.

## Module naming call (task 5.1 explicitly left this to the implementer)

Task 5.1 says the `aipc-agent-gate.service` unit could be "shipped by
`agent-orchestrator` or its own helper file under
`agent-screen-control`/`agent-orchestrator`". None of those was available
this session — `agent-orchestrator` and `agent-screen-control` were both
being actively edited in parallel by other dispatches at the same time
(same repo, `agent-screen-control` building against this module's RPC
contract) — so folding the gate into either would have collided. Shipped
as its own module instead, named `agent-gate` (matches the service name
`aipc-agent-gate.service` exactly, same convention as `agent-orchestrator`
-> `aipc-agent-orchestrator.service`, `agent-browser`, `agent-code-shell`).
Not `agent-tools-gate` or `agent-permission-gate` (both considered) — this
isn't a "tool" a sub-agent calls to do work, it's the authorisation layer
every risky tool call checks against, so a name that mirrors the unit
directly reads clearer. This adds a 9th module to Phase 4 / a 46th module
overall (see `docs/architecture.md` §7, bumped 45->46) — no existing slot
was reserved for it, unlike the `ccs` precedent (`docs/agent-log.md`
2026-07-04) which reconciled a module that already existed unlisted.

## Wire protocol

UNIX socket at `/run/aipc-agent-gate.sock`, newline-delimited JSON, one
request line in, one response line out (boring and sufficient for a
single-machine single-writer socket — no gRPC/protobuf).

```
{"cmd": "grant", "actions": [...], "scope": "session"|"task",
 "duration_seconds": <int, session only>, "task_id": <str, task only>}
  -> {"grant_id": "...", "expires_at": <float>|null, "task_id": <str>|null}

{"cmd": "revoke", "grant_id": "..."}
{"cmd": "revoke", "task_id": "..."}   # bulk: every task-scope grant for that id
  -> {"revoked": <count>}

{"cmd": "check", "action": "screen-control"}
  -> {"allowed": true|false, "grant_id": <str>|null}

{"cmd": "status"}
  -> {"grants": [{"grant_id", "actions", "scope", "expires_at", "task_id",
                   "granted_at"}, ...]}   # non-expired only

# any error (bad cmd, missing/invalid field) -> {"error": "..."}
```

Socket is `chmod 0666` — single-user trusted-machine model (CLAUDE.md
§0/§6, design.md D5: "no real security concern"), so a non-root `aipc
agent gate ...` CLI call works without sudo.

## Implemented (tasks 5.1, 5.2, 5.4, 5.5)

- `files/usr/lib/aipc-agent/aipc_agent_gate/store.py`: `GrantStore` —
  in-memory dict (`grant_id -> {actions, scope, expires_at/task_id,
  granted_at}`) backed by SQLite (`/var/lib/aipc-agent/gate.db`) for
  restart persistence. On start, loads still-valid grants back into
  memory: task-scoped grants always (no time bound, only explicit
  revoke ends them); session-scoped grants only if `expires_at` hasn't
  passed yet.
  - `check()` is the hot path every gated action calls: pure in-memory
    scan, **no SQLite hit**. An expired session grant is denied purely by
    comparing `expires_at` against `time.time()` — correctness doesn't
    depend on anything having purged it yet.
  - `sweep_expired()`: a background thread (`server.py`, 30s interval)
    calls this to purge expired session grants from memory + SQLite.
    **ponytail**: this is hygiene (keeps a long-lived daemon's grant table
    and SQLite file from accumulating dead rows), not correctness — `check()`
    is already correct without it via the timestamp comparison above.
    Upgrade path if this daemon's grant count ever gets large enough to
    matter: index `check()` by action instead of a full dict scan;
    irrelevant at this daemon's actual scale (single-user machine, low
    tens of grants).
  - `revoke(task_id=...)` bulk-revokes every `scope: "task"` grant for
    that id in one call (task 5.4's RPC verb). Wiring an actual "supervisor
    reports task done" signal into `agent-orchestrator`'s graph is
    explicitly out of scope here — a follow-up integration task once that
    graph exists; this module only guarantees the RPC verb itself is
    correct, verified directly (see Verification below).
- `files/usr/lib/aipc-agent/aipc_agent_gate/audit.py`: append-only JSON
  Lines at `/var/log/aipc-agent-gate.jsonl` (task 5.5) — one line per
  grant, per check (both allow and deny), per revoke. A write failure
  (disk full, permission) is caught and logged to stderr rather than
  crashing the request — the audit trail is best-effort, the actual
  safety mechanism (grant/check/revoke) must survive an audit-log fault.
- `files/usr/lib/aipc-agent/aipc_agent_gate/server.py`: the RPC dispatch
  (`handle_request`), a `socketserver.ThreadingMixIn` +
  `UnixStreamServer` (thread-per-connection, stdlib only), and `main()`
  (also starts the sweep thread). `self_test()` / `--self-test` drives
  `GrantStore` + `handle_request` directly (no real socket — the socket is
  a thin transport, the dispatch logic is what matters and this is far
  less flaky): session grant with `duration_seconds=0` -> immediately
  denied; a real-duration session grant -> allowed, then explicitly
  revoked -> denied again; task-scope grant -> allowed, bulk-revoked by
  `task_id` -> denied; unknown cmd raises; a still-valid grant survives a
  simulated restart (new `GrantStore` against the same SQLite file).
- `files/etc/systemd/system/aipc-agent-gate.service`: native systemd unit
  (not a container — nothing here needs sandboxing, same reasoning as
  `agent-orchestrator`), `ExecStart=/usr/bin/python3 -m
  aipc_agent_gate.server` directly against system Python — **no venv**,
  unlike `agent-orchestrator`: this module is deliberately stdlib-only
  (`socket`, `socketserver`, `sqlite3`, `json`, `threading`), so a venv
  would be pure overhead.
- CLI (task 5.2): `tools/aipc_lib/gate_client.py` (thin socket client,
  same wire protocol) + `aipc agent gate {grant,revoke,status}` in
  `tools/aipc_lib/cli.py`. `grant --scope session <duration-seconds>
  --actions a,b,c` / `grant --scope task <task-id> --actions a,b,c` /
  `revoke --grant-id <id>` / `revoke --task-id <id>` / `status`.

## Task 5.3 (`aipc agent screen --mode ...`)

Out of scope here by design — it's a thin wrapper over this module's
generic `aipc agent gate grant --actions screen-control ...`, specific to
`agent-screen-control` framing, and that module was being built in
parallel this session. Verified that the wrapper's expected building
block works: `aipc agent gate grant --scope session <seconds> --actions
screen-control` round-trips correctly against the live daemon (see
Verification).

## Consuming this from `agent-tools-files`

`agent-tools-files/files/usr/lib/aipc-agent/aipc_agent_tools_files/tools.py`'s
`check_gate_grant()` was a fail-closed stub (no gate existed yet) whose own
docstring named this exact upgrade path. Updated it to speak this
module's real wire protocol (JSON over the socket, not the placeholder
plaintext `"check <action>\n"` / `b"GRANTED"` it used to send) — verified
live: granting `files.delete` then calling `check_gate_grant('files.delete')`
against the running daemon returns `True`; after revoking, `False` again.
`delete()` itself needed no changes, exactly as that module's prior
upgrade note predicted. This was the only file outside `modules/agent-gate/`
touched this session (plus its README's note describing the same thing).

## Verification

**Hardware-verified 2026-07-06** (on the real Strix Halo AI PC — this
machine's own `/proc/cpuinfo` confirms `AMD RYZEN AI MAX+ 395`), full
round trip, both directly and via a real live-hotfixed systemd unit:

1. Ran the daemon module directly (`aipc_agent_gate.server.main()`) as
   root bound to the real production socket path
   `/run/aipc-agent-gate.sock`; confirmed `chmod 0666`.
2. `aipc agent gate grant/status/revoke` (real CLI, unprivileged user)
   round-tripped against it: session grant -> `status` shows it -> revoke
   -> gone. Task-scope grant -> `revoke --task-id` bulk-revokes it.
3. Live-hotfixed a real systemd unit (`docs/live-hotfix-workflow.md`
   pattern — `/usr` is read-only ostree on this un-rebuilt machine, so
   `ExecStart`'s `PYTHONPATH` points at `/var/lib/aipc-agent` instead of
   the repo's real `/usr/lib/aipc-agent` path, same workaround already
   documented for `agent-orchestrator`). `systemctl enable --now
   aipc-agent-gate.service` -> active; a 2-second session grant expired on
   its own wall-clock time (`status` showed it, then empty after
   sleeping past expiry) — confirms real time-bounded expiry, not just
   the self-test's `duration_seconds=0` shortcut.
4. `/var/log/aipc-agent-gate.jsonl` captured one line per grant/check/
   revoke across the whole session, correctly interleaved, no crashes.
5. `sweep_expired()` verified directly: an expired session grant is
   purged from both memory and SQLite; a still-valid one survives.
6. `modules/agent-gate/verify.sh` run against the live service: static +
   self-test + a real socket `status` round trip, all green.

**Not verified**: `aipc-agent-gate.service` starting via the repo's own
`ExecStart=/usr/bin/python3 -m aipc_agent_gate.server` with
`PYTHONPATH=/usr/lib/aipc-agent` (the actual shipped unit) — that path
doesn't exist on this machine until a real `bootc switch` (same gap
`agent-orchestrator`'s own README documents); the live-hotfix unit above
is functionally identical (same module code, same socket path, only the
`PYTHONPATH` differs) and was used instead per
`docs/live-hotfix-workflow.md`. Live-hotfix unit and package under
`/etc/systemd/system/` and `/var/lib/aipc-agent/` were left running/in
place per that doc's convention (scratch artifacts for verification, not
committed).

## Dependencies
- system-base

## Spec
openspec/changes/phase-4-agent — tasks 5.1, 5.2, 5.4, 5.5 done here; 5.3
(`aipc agent screen`) is a thin wrapper left to `agent-screen-control` or
a follow-up; the actual supervisor->gate "task done" signal wiring into
`agent-orchestrator` remains a follow-up integration task.
