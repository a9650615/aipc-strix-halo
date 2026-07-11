# How

- Put result bounding at the shared tool-result insertion point. Write the full
  result first, then persist a bounded head/tail representation in the session.
- Keep `context_length: 131072`, `compression.threshold: 0.70`, the compact
  auxiliary timeout at LiteLLM's 600-second request ceiling, and reduce the
  protected tail to four messages.
- Treat an unrecoverable compression result as a session lifecycle event.
- Build the handoff from bounded structured fields; use the existing compact
  lane when available and a deterministic formatter on failure.
- Carry a pending user message only before its model/tool execution starts.
- Reuse the existing session store and notification surface. Add no service or
  dependency.
