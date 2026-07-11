# Hermes Context Rollover Design

## Problem

Hermes declares the backend's real 131,072-token window, but a large protected
tail can leave the compressor with nothing safe to remove. Large tool results
make this likely: compression then reports `Cannot compress further` even when
the number in that message is well below 131,072. Raising the declared window
would only postpone compression beyond the backend's actual limit.

## Chosen behavior

Hermes keeps `model.context_length: 131072`, starts compression at 70% of the
usable input window, and protects the last four messages. Tool results that
would consume an excessive share of the prompt are represented by bounded
head/tail text plus a path to the complete local artifact.

If compression still cannot produce a valid prompt, Hermes creates a successor
session. A bounded handoff records the active goal, current state, changed
files, checks run, and unresolved errors. Hermes carries the pending user
message only when no model/tool execution for that message has begun, then
shows one notice that the session was rolled over.

## Safety

- Never declare a context window larger than the backend provides.
- Never discard the complete tool result; store it locally before replacing it
  with a prompt-sized representation.
- Never replay a tool call or other side effect during rollover.
- If handoff generation fails, create a deterministic bounded handoff rather
  than retaining the oversized history.
- Keep the predecessor session available for audit and manual resume.

## Implementation boundary

The fix belongs in Hermes' shared context/session path so direct CLI and
orchestrator callers behave identically. The repository owns reproducible
configuration and patch deployment; no new daemon or dependency is needed.

## Verification

Unit tests cover tool-result bounding, safe pending-message carryover,
side-effect non-replay, one-time notification, and deterministic handoff
fallback. A synthetic context test crosses the 70% threshold and forces an
unrecoverable protected tail. Static and both render targets must pass. A real
128K-class Hermes session on the Strix Halo host is required for the final
hardware-verified claim.
