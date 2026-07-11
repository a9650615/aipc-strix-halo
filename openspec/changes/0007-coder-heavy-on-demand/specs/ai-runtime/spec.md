## ADDED Requirements

### Requirement: Heavy On-Demand Coding Alias

The runtime SHALL provide a `coder-heavy` alias backed by a ~100B-class local
MoE model that fits entirely in GPU-addressable unified memory (no expert,
layer, or disk offloading). The alias SHALL be on-demand: never pinned,
loaded by Lemonade on first inference, and unloaded by the idle-release
policy (`idle_unload_after_s: 600`) after ten idle minutes.

#### Scenario: coder-heavy loads on demand and releases after idle

- **WHEN** a request names `coder-heavy` while it is not loaded
- **THEN** Lemonade loads it and serves the request, and after 600 seconds
  with no further traffic the idle-release job unloads it

#### Scenario: steady-state fleet leaves headroom for the heavy lane

- **WHEN** `ornith-35b` and `assistant-gemma` have been idle past their
  declared `idle_unload_after_s`
- **THEN** the resident set is at most the pinned NPU model plus
  `coder-agentic`, leaving enough free unified memory to cold-load
  `coder-heavy` without invoking the oom-killer

#### Scenario: heavy lane does not displace the main lane

- **WHEN** `coder-heavy` is loaded or serving
- **THEN** `coder-agentic` remains loaded and continues to serve requests
  on its own slots
