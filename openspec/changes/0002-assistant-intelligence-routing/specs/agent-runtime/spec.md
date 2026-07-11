# agent-runtime Specification Delta

## MODIFIED Requirements

### Requirement: Multi-Agent Supervisor With Four Shipped Sub-Agents

The `agent-orchestrator` module SHALL provide a LangGraph supervisor and the
shipped Researcher, Coder, Browser, and Daily Assistant worker graphs. A single
assistant-intelligence-routing authority SHALL produce the transport-neutral
RouteDecision before worker execution. The aggregator, supervisor, and workers
SHALL NOT independently reclassify the same turn; they MAY reject an execution
whose required capability or grant is no longer available and return a
structured reason for replanning.

Workers SHALL bind to stable role/capability aliases rather than concrete model
or provider names. They SHALL report capabilities and normalized progress,
tool-request, result, usage, verification, and error events to the shared
session. Parallel fan-out and result merging remain responsibilities of the
LangGraph supervisor, not the routing-decision component.

#### Scenario: One decision per turn

- **WHEN** a normalized turn reaches the orchestrator
- **THEN** exactly one versioned RouteDecision SHALL be persisted and used by
  the executor unless a structured capability change requires explicit replan

#### Scenario: Worker binding is role-stable

- **WHEN** a worker starts with no explicit model override
- **THEN** it SHALL request its stable role/capability alias and SHALL NOT embed
  a concrete vendor model ID or backend URL

#### Scenario: Runtime capability disappears

- **WHEN** the selected worker or required tool becomes unavailable after the
  RouteDecision
- **THEN** execution SHALL return a structured `capability_unavailable` event
  and the router SHALL replan within the original grants and deadline

## ADDED Requirements

### Requirement: Subscription And Proxy Agents Obey Agent Permission Gates

Subscription CLI and optional proxy adapters SHALL execute only through the
agent executor with an explicit working directory, allowed data scopes, tool
permissions, deadline, turn limit, cancellation handle, and idempotency key.
Remote-use approval SHALL NOT grant filesystem, shell, browser, screen, or
external-side-effect permission.

#### Scenario: Remote coding agent receives repository scope

- **WHEN** a user grants a subscription agent access to one repository for a
  coding task
- **THEN** the adapter SHALL scope its working directory and filesystem grant
  to that repository and SHALL deny access outside the grant

#### Scenario: Delegated coding change may commit but not publish

- **WHEN** a user confirms a Codex, Claude Code, or Grok Build coding task
- **THEN** the adapter MAY allow edits and commits on the scoped task branch
  but SHALL deny `git push`, merges, and equivalent publication operations

#### Scenario: Controlled CLI is visible

- **WHEN** an assistant-controlled CLI process is starting, running, waiting,
  cancelling, or finishing
- **THEN** the local dashboard SHALL expose its provider, repository/worktree,
  branch, process identity, elapsed time, last activity, and terminal state
  without exposing the prompt, credentials, or command environment

#### Scenario: Failover after side effect

- **WHEN** a provider fails after a side-effecting tool action completed
- **THEN** failover SHALL NOT replay that action; it MAY replan from the
  normalized tool result using the same idempotency record
