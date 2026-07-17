# How — peer-mcp-progress-observability

## Architecture

The existing peer MCP `_run()` helper is the instrumentation boundary. It
continues owning process creation, timeout, and stop behavior, but drains both
pipes incrementally and appends bounded lifecycle records to a user-only
JSONL journal. All four public dispatch paths use this helper, so the event
contract is not duplicated per provider.

The portal remains read-only. Its `agents.py` reader folds the journal by
`agent_id`, checks PID liveness for unfinished records, and merges the result
into the existing agents snapshot. The existing ETag poller is sufficient for
the first version; no second transport is introduced.

## Event rules

- `started` is emitted only after `Popen` returns a PID.
- `output` contains only a clipped, control-character-scrubbed tail.
- `heartbeat` is emitted while a process is alive even when it is silent.
- Exactly one terminal event is emitted for normal exit, non-zero exit,
  timeout, or explicit stop.
- A crashed MCP process may leave a non-terminal record; the portal folds it to
  `stale` only when the PID is no longer alive.
- Journal read failures are optional-source failures and return an empty list.

## Data safety

The journal does not persist the prompt, environment, auth files, or complete
command arguments. Writes are bounded and user-only. The portal must tolerate
partial final lines and malformed JSON without failing `/api/v1/agents`.

## Testing

- Unit-test journal folding, status transitions, clipping, malformed lines,
  stale PID handling, and bounded output with temporary files.
- Exercise the shared runner with a small local Python subprocess that emits
  stdout/stderr, sleeps, exits non-zero, and can be stopped.
- Test `/api/v1/agents` and the SPA contract with a JSONL fixture.
- Run focused pytest, Python syntax checks, OpenSpec strict validation, and the
  repository's bootc/ansible render-parity checks.
- A real subscription CLI run remains hardware/runtime verification only.
