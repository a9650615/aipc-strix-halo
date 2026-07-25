# Assistant Capability-to-Worker Routing

## Context

The assistant aggregator currently decides whether a request needs the agent
with a second, incomplete keyword list. Requests such as `找頭條新聞` therefore
go directly to `resident-small`, even though the authoritative router already
recognizes live news as a grounded web-search task. This creates two routing
authorities and prevents the tool-capable worker from seeing the request.

The repository's lane decision in change 0011 makes `coder-agentic` the
resident 35B for Daily Assistant and Hermes tasks. `ornith-35b` is on-demand
and idle-released for skill learning and technical advice, so it is not the
default interactive task worker.

## Goals

- Make the authoritative agent router the only capability decision point for
  local fulfillment requests.
- Route live web/news lookup to Daily Assistant, whose bound tools run on
  `coder-agentic`.
- Route explicitly deep, multi-step research to Hermes, also using
  `coder-agentic` by default.
- Keep `ornith-35b` out of the hot path until a separate quality-based
  escalation policy and hardware evidence exist.
- Preserve local control actions and an explicit strict-NPU opt-out.

## Design

```text
aggregator control actions ────────────────> local action handlers
                                             
aggregator fulfillment ──> agent :4100 ──> authoritative capability router
                                                  │
                             chat/control ────────┴──> supervisor
                             web/news/search ─────────> Daily Assistant / coder-agentic
                             deep multi-step research > Hermes / coder-agentic
```

The aggregator's default `auto` mode sends fulfillment text to the agent
endpoint. It no longer decides this through `_needs_agent_capabilities()`.
`mode: npu` remains an explicit degraded/strict-NPU mode for users who accept
no tools. The aggregator still handles its existing allow-listed control
actions before fulfillment.

The router's deterministic analysis adds a `research` capability for explicit
deep or multi-step research phrasing. Plain live/current/news requests remain
`web_search + grounding` and select `local-daily`; `research` adds the
`local-hermes` stage. `coder-agentic` is already the Daily Assistant model and
becomes Hermes's default model as well. No new dependency or model alias is
introduced.

## Failure behavior

- If the agent endpoint is unavailable, aggregator `auto` reports the agent
  error; it does not silently answer a tool-shaped request with an ungrounded
  NPU reply.
- If the search backend is unavailable, the existing tool status reaches the
  model and the assistant reports that it could not verify the result.
- `ornith-35b` remains available to its existing advisor/learning paths only;
  using it as an interactive fallback requires a later OpenSpec decision and
  hardware verification.

## Tests

- Router analysis: `找頭條新聞` and `搜尋今日新聞` require live web grounding.
- Authoritative plans: ordinary news selects `daily_assistant`; explicit deep
  research selects `hermes`.
- Aggregator: default `auto` sends even ordinary fulfillment to the agent;
  strict `npu` remains local.
- Existing router, aggregator, and agent tests remain green.

## Verification

Static verification covers the focused pytest suite and lint/schema checks.
Render verification covers both bootc and Ansible targets because the touched
files belong to two modules. Hardware verification is required before claiming
runtime web search or model-load behavior works on the Strix Halo machine.
