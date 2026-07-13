## ADDED Requirements

### Requirement: Reclaim Externally-Reclaimable GPU Memory Before Swap-Backed Admission

When gateway admission control cannot fit a target model after evicting every
eligible LLM victim, and the remaining pressure is non-LLM GPU memory held by a
reclaimable external consumer (ComfyUI), the scheduler SHALL request that
consumer release its cache — but ONLY while that consumer is idle — before
falling back to swap-backed admission. Reclaim SHALL fire at most once per
admission, SHALL never interrupt a running external job, and SHALL degrade open
(a missing, unreachable, or erroring consumer is skipped silently, leaving the
0012 evict → swap → hold path unchanged). Reclaim is disabled unless the
consumer endpoint is explicitly configured.

#### Scenario: Idle ComfyUI cache reclaimed before swap

- **WHEN** a target model does not fit, no evictable LLM remains, and a
  configured ComfyUI reports an empty queue
- **THEN** the scheduler asks ComfyUI to free its cache once, waits one poll
  interval, and re-checks fit before considering swap-backed admission

#### Scenario: Running ComfyUI job is never interrupted

- **WHEN** the same pressure exists but ComfyUI reports a running or pending job
- **THEN** the scheduler does not request a reclaim and falls through to the
  existing swap-backed admission / hold path

#### Scenario: Reclaim is a last resort after eviction, not before

- **WHEN** an evictable LLM victim still exists
- **THEN** the scheduler unloads the LLM victim and does not request a ComfyUI
  reclaim on that iteration

#### Scenario: Reclaim degrades open

- **WHEN** no ComfyUI endpoint is configured, or the configured endpoint is
  unreachable or errors on the queue/free calls
- **THEN** admission proceeds exactly as without reclaim (evict → swap → hold),
  and the scheduler never blocks or fails on the external consumer's behalf
