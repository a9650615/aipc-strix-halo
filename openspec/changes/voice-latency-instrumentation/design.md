## Context

The perceived-latency fix is `voice-streaming-turn`; this change only supplies
the measurement needed to verify it. Scope is deliberately minimal: three
headline durations per turn, one shared recorder called by both the batch path
(`aipc-voice-once`, the baseline streaming must beat) and the streaming worker.
Stdlib only (§8), no behavioural change, near-zero overhead. Analytics are
deferred — there is no turn data yet to design a report against.

## Stage model (minimal)

Only the marks needed for the three headline numbers are required; others are
optional and left null.

```
 capture_end ─────────────────────────────► play_start ──► play_done
      │                                          ▲
      │        llm_request ─► llm_first_token     │  (stream only)
      │                    └─► llm_done            │
      │        tts_request ─► tts_first_audio ─────┘

 Headline durations:
   perceived = play_start      - capture_end     ← the number users feel
   llm_ttft  = llm_first_token - llm_request     ← stream only; null on batch
   tts_ttfa  = tts_first_audio - tts_request
```

`perceived` is computable from the batch path today; it is the baseline the
streaming turn must lower. `llm_ttft` is null until the streaming worker exists.

## Decisions

### D1: One JSONL line per turn to an XDG state file

Append one JSON object per completed turn to
`${XDG_STATE_HOME:-~/.local/state}/aipc-voice/turns.jsonl`.

- **Alternatives considered**:
  - *journald structured fields* — ties reading to `journalctl`, awkward for a
    quick tail; rejected.
  - *stdout only* — lost after the turn; rejected.
  - *sqlite* — a DB dependency for an append-only log; rejected (§8).
- **Why**: a flat JSONL file is trivially tailed by the reader and by `jq`,
  survives reboots, needs no daemon.

### D2: Single shared `TurnTimer` recorder

A small stdlib object with `.mark(stage)` (`time.monotonic_ns()`),
`.context(**labels)`, and `.flush()` (write at turn end). Both
`aipc-voice-once` and the streaming worker mark against the same object so the
batch-vs-stream comparison is apples-to-apples.

- **Alternatives considered**:
  - *scattered `time.time()` calls* — duplicated derivation, drifts between
    paths; rejected.
  - *tracing library / decorators* — new dependency and coupling; violates §8.
- **Why**: one seam, derivation defined once, reused by both paths.

### D3: Minimal context label, not full analytics

Each record carries only `path` (`batch`/`stream`), `tts_backend`, `preset`,
plus fallback outcome flags — enough to label a turn, not to slice a dataset.

- **Alternatives considered**:
  - *rich per-turn metadata for later grouping* — speculative; there is no
    consumer for it yet; rejected as premature (§8 YAGNI).
- **Why**: the only comparison needed now is "this stream turn vs a batch turn
  under the same backend/preset". Richer breakdown lands when the arbiter needs
  it.

### D4: Best-effort, write-once, never in the hot path

Marks are cheap memory writes; the only IO (one file append) happens once at
turn end inside a `try/except` that swallows every error.

- **Alternatives considered**:
  - *per-stage flush* — repeated disk IO inside the latency path being
    measured (observer effect + failure risk); rejected.
- **Why**: instrumentation must never be the reason a turn is slow or fails.

### D5: Raw-tail reader only (analytics deferred)

`aipc voice timings [--last N] [--json]` prints the most recent N records (raw
rows + a simple mean of the headline durations). No percentiles, no `--by`
grouping.

- **Alternatives considered**:
  - *p50/p95 + per-preset/backend breakdown now* — builds an analysis backend
    before a single turn exists to analyze; the original over-engineered draft;
    rejected. The raw JSONL still allows ad-hoc `jq` for anyone who wants more.
- **Why**: the job now is "show the three numbers so streaming can be
  verified", not "run a fleet analysis". Defer the report until it has data and
  a real consumer (the arbiter).

### D6: Disable via env, schema-stable optional marks

`AIPC_VOICE_TIMING=0` disables recording. Missing marks are null; the streaming
first-token mark fills in when the streaming worker lands — no schema change.

- **Alternatives considered**:
  - *always on, no opt-out* — a single env flag is free insurance for
    debugging / privacy-sensitive runs.

## Risks

- **Hot-path overhead / observer effect → Mitigation**: only `monotonic_ns()`
  memory writes during the turn; a single best-effort file append at turn end;
  `AIPC_VOICE_TIMING=0` fully disables.
- **Logging IO error aborts or delays a turn → Mitigation**: `.flush()` wrapped
  so any exception is swallowed; the turn result is independent of the write.
- **Unbounded log growth → Mitigation**: size cap on write (drop oldest,
  default ~5000 turns); covered by a unit test.
- **Privacy: leaking spoken content → Mitigation**: schema stores only
  durations + categorical labels; a unit test asserts no transcript/reply
  field is ever written.
- **Scope creep back into analytics → Mitigation**: reader is a raw tail by
  design; percentiles/grouping are an explicit non-goal recorded here and in
  the proposal, to be raised only when the arbiter work needs them.
- **`llm_ttft` meaningless on batch path → Mitigation**: optional/null;
  `perceived` alone gives the batch baseline streaming must beat.
