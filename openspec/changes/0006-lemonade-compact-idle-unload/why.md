# Why: Compact Lane Should Release Itself After Going Idle

`coder-compact` is a deliberately on-demand compact lane. It exists to keep
short summaries, auto-compact passes, and other light-weight work off the
heavier `coder-agentic` / `ornith-35b` slots.

Today it can stay loaded indefinitely once used, because Lemonade does not
ship a built-in per-model idle eviction policy. That is acceptable for the
resident main models, but wasteful for a lane that is only useful while
something is actively compacting. The result is avoidable iGPU/GTT pressure
and a model slot that remains occupied for no benefit after the session ends.

The desired behaviour is simple: if `coder-compact` has been idle for five
minutes, release it. The design should stay extensible so later models can opt
into the same policy without reworking the mechanism.
