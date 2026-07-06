# agent-tools-files

File-IO tools (read/write/list/delete) for agent sub-agents (D5), plus the
path allowlist every one of them checks before touching the filesystem.

## Current status: basic implementation, un-disabled

This is a pure-Python library, not a daemon — there's no runtime service to
enable/disable, so the `.disabled` convention (CLAUDE.md §9) doesn't apply
the way it does to a service module. **Verification reached here is static
only** (Python syntax check + the self-test below) — there is no hardware
dependency to verify beyond that, but also nothing has actually exercised
this from a real LangGraph sub-agent yet (task 2.4, Coder sub-agent, is
what will do that). Don't read "un-disabled" as "hardware-verified."

Implemented (task 4.1):
- `files/usr/lib/aipc-agent/aipc_agent_tools_files/tools.py`:
  `read_file`, `write_file`, `list_dir`, `delete`. Every call resolves the
  given path (`Path.resolve()`, follows symlinks) and checks it against the
  allowlist roots **before** any syscall; a path resolving outside every
  root raises `AllowlistViolation` (never silently clamped/truncated).
- Allowlist roots come from `/etc/aipc/agent-tools/files-allowlist.conf`
  (one absolute path per line, `#` comments), or a single default root
  `/var/lib/aipc-agent/workspace` if the file is missing/empty.
  `roots[0]` is the "workspace" — `delete` there needs nothing extra.
- `delete` on a path that only resolves inside a later (non-workspace)
  root calls `check_gate_grant("files.delete")` first.
  **Updated 2026-07-06**: `aipc-agent-gate` (phase-4-agent#5.1) now exists
  as `modules/agent-gate/` — `check_gate_grant()` speaks its real wire
  protocol (newline-delimited JSON `{"cmd": "check", "action": ...}` ->
  `{"allowed": bool, ...}` over `/run/aipc-agent-gate.sock`), verified live
  against the running daemon (grant `files.delete` -> check returns
  `True`; revoke -> check returns `False` again). Any connection failure
  or malformed response is still treated as "no grant" — fail closed, not
  fail open. `delete()` itself needed no changes, exactly as the prior
  upgrade note predicted.
- Self-test (`python -m` style, matches `system-memory-oom-guard`'s
  `--self-test` convention): `tools.py --self-test` exercises accept /
  path-traversal-reject / symlink-escape-reject / gate-fail-closed-delete
  in one assert-based run. `verify.sh` calls it.

## Design decisions to double-check
- **Allowlist default root** is `/var/lib/aipc-agent/workspace` (a fixed
  system path), not the task-4.1-prompt's example `~/aipc-workspace` or
  the original task-1.5 scaffold's `~/projects` + `~/Documents`. Reason:
  `aipc-agent-orchestrator.service` (the process that will end up calling
  these tools) has no `User=` in its unit, so it runs as root — `~`
  resolving to `/root` for a shared agent workspace seemed like the wrong
  default. There's no repo-wide convention yet for resolving "the primary
  user" from a running root service (the existing `AIPC_PRIMARY_USER` /
  `SUDO_USER` pattern in `modules/dev-cli/post-install.sh` is build-time
  shell only). A fixed `/var/lib` path sidesteps that gap entirely. If a
  primary-user-resolution convention lands later, revisit this default.
- Config file path used is `/etc/aipc/agent-tools/files-allowlist.conf`,
  matching the path task 1.5 in `tasks.md` actually names (and the sibling
  `agent-tools-calendar` module's `/etc/aipc/agent-tools/calendar.yaml`
  convention) — not the `/etc/aipc/agent/files-allowlist.yaml` the earlier
  task-1.5 scaffold shipped. The old file/path is removed.
- Format is a plain `#`-commented path list, not YAML — this module has no
  pip dependency (task 4.1 says stdlib is enough), and adding `PyYAML` just
  to parse a list of roots isn't worth a new dependency.
- `delete` on a directory only calls `rmdir()` (empty dirs only), no
  recursive `shutil.rmtree` — smaller blast radius for a first cut; add
  recursive delete if/when a sub-agent actually needs it.

## Consuming from agent-orchestrator
`aipc_agent_tools_files` installs as a sibling top-level package under
`/usr/lib/aipc-agent/`, the same directory `agent-orchestrator` already
puts `PYTHONPATH` on (see its systemd unit's
`Environment=PYTHONPATH=/usr/lib/aipc-agent`). Once a sub-agent graph
exists (task 2.4, Coder), it imports directly:
```python
from aipc_agent_tools_files import read_file, write_file, list_dir, delete
```
No venv/site-packages wiring needed — pure stdlib, same PYTHONPATH already
in place.

## Dependencies
- system-base

## Spec
openspec/changes/phase-4-agent — task 4.1 (this module's tools);
task 1.5 scaffolded the module shell.
