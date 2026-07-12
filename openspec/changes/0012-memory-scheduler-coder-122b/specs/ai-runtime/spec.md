## ADDED Requirements

### Requirement: Gateway Admission Control For Local GPU Model Loads

Every chat request routed through the LiteLLM gateway to a local Lemonade GPU
model SHALL pass memory-budget admission control before being forwarded. A
request whose target model is not loaded SHALL be forwarded only once the
target fits a configured GPU memory budget, evicting lower-priority loaded
models if needed; otherwise the request SHALL be held (not forwarded) until it
fits or a hold deadline elapses. Admission decisions SHALL be serialized so
concurrent requests cannot interleave evictions.

#### Scenario: Fit passes through untouched

- **WHEN** a request targets a model that is already loaded
- **THEN** the request is forwarded immediately with no scheduling action

#### Scenario: Over-budget load evicts by priority

- **WHEN** a request targets an unloaded model whose size exceeds the free
  budget
- **THEN** the scheduler unloads floating-tier models (LRU first) before
  resident-tier models, never an in-use model, until the target fits

#### Scenario: Unsatisfiable load is held, not queued into lemond

- **WHEN** the target cannot fit even after eviction (victims in use)
- **THEN** the request is held at the gateway and re-evaluated; lemond never
  receives a load it cannot satisfy; after the hold deadline the gateway
  returns an error naming the scheduler

#### Scenario: Scheduler failure degrades open

- **WHEN** the lemonade health endpoint is unreachable
- **THEN** requests pass through unchanged (no new single point of failure)

### Requirement: Exclusive-Tier Model Class (`coder-122b`)

The manifest SHALL support `tier: exclusive | resident | floating` for
Lemonade GPU models. An exclusive-tier target MAY evict resident-tier models
and MAY bypass eviction cooldown; non-exclusive targets SHALL NOT evict
resident-tier models. `coder-122b`
(SC117/Qwen3.5-122B-A10B-Uncensored-APEX-Compact, main + mmproj) SHALL be
registered as exclusive-tier with `idle_unload_after_s: 600`.

#### Scenario: coder-122b preempts the agent fleet

- **WHEN** a request targets `coder-122b` while resident agents occupy the
  budget
- **THEN** floating then resident models are unloaded until 55.1 GiB + margin
  fits, and only then does the load proceed

#### Scenario: Agents yield while the exclusive model works

- **WHEN** an agent-lane request arrives while `coder-122b` is loaded and in
  use
- **THEN** the agent request is admitted only into leftover budget (small
  models) or held — `coder-122b` is not evicted

### Requirement: Resident Set Restore After Exclusive Sessions

When no exclusive-tier model is loaded, the idle-release daemon SHALL re-warm
unloaded resident-tier models (budget-checked, without evicting anything), so
the agent fleet returns to steady state after an exclusive session ends.

#### Scenario: Post-122B restore

- **WHEN** `coder-122b` idle-releases after 600 s and resident models were
  evicted during its session
- **THEN** subsequent daemon cycles reload the resident set one model per
  cycle until steady state is restored
