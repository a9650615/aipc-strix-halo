# Hermes Dynamic MoA Design

## Goal

Every Hermes entry point and delegated agent can ask one or more configured
advisor models for a second opinion only when the acting agent decides it is
useful. Hermes remains the acting model and synthesizes the advisor output.
The first advisor is the existing monthly-subscription Z.AI GLM alias.

## Decision

Use Hermes's official external-tool extension path: one local stdio MCP server
registered globally as `mcp-dynamic-moa`. Do not modify Hermes core and do not
select Hermes's MoA provider, because the provider fans out on every model
iteration rather than on demand.

The server exposes one tool:

```text
consult_models(question, advisors=["glm"])
```

`question` is the agent-curated problem plus only the code or context the
agent considers necessary. `advisors` is validated against the server-side
advisor registry. The initial registry contains only `glm`, mapped to LiteLLM
alias `glm-cloud`. Hermes itself is the aggregator; the MCP server returns
advisor-labelled responses and never makes a separate aggregator call.

## Availability

Hermes creates a dynamic `mcp-dynamic-moa` toolset for the server. Provisioning
adds that toolset to every configured `platform_toolsets` entry. Delegated
agents inherit their parent's MCP toolsets, so CLI, messaging gateways, leaf
subagents, and nested orchestrator agents receive the same tool.

The existing Daily Assistant `ask_glm` tool remains available and reuses the
same quota/call core. It is not the Hermes integration point.

## Data and Safety Boundary

The tool receives only the explicit `question` argument, never the full Hermes
transcript, memory, filesystem, or tool results automatically. Agents may put
necessary code snippets or selected working context in the question.

Before dispatch, the shared core masks credential-shaped substrings such as
API keys, bearer tokens, and password assignments. It does not run a broad
personal-data classifier, private-context taint system, or moderation model.
The tool description tells agents to keep likely provider-moderated requests
local. This is guidance rather than a second content-policy engine.

Foreground and background Hermes agents may call the tool. Unknown advisors,
empty questions, unavailable credentials, stale/unknown/exhausted Z.AI quota,
LiteLLM errors, and provider errors fail soft with a structured result; Hermes
continues locally.

## Call Path

```text
Hermes agent or subagent
  -> consult_models MCP tool
  -> validate advisor + mask credentials
  -> CodexBar `zai` quota snapshot
  -> LiteLLM `glm-cloud`
  -> labelled advisor response
  -> calling Hermes agent synthesizes or ignores it
```

No direct Z.AI call is allowed from Hermes or the MCP server. The existing
LiteLLM alias and SOPS-provisioned `Z_AI_API_KEY` remain the only provider
boundary.

## Configuration and Lifecycle

The reproducible module owns the MCP server executable and the Hermes config
fragment. Live configuration is updated through the documented live-hotfix
workflow, then `/reload-mcp` or a coordinated Hermes restart refreshes tool
discovery. The API key is never copied into Hermes config or MCP environment;
the call continues through local LiteLLM.

## Verification

- Unit test advisor validation, credential masking, quota fail-soft behavior,
  and successful labelled output.
- Test MCP tool discovery and one tool call against a stubbed shared core.
- Verify generated Hermes config enables `mcp-dynamic-moa` for every platform.
- Verify a delegated child inherits the MCP toolset using the installed Hermes
  delegation behavior.
- Render both bootc and Ansible targets.
- On hardware, run `hermes mcp test dynamic-moa`, call from a normal Hermes
  session and a delegated child, then confirm CodexBar quota changes and local
  work still succeeds when GLM is unavailable.

## Non-Goals

- Automatically invoking advisors on every Hermes iteration.
- Switching the acting Hermes model.
- Adding a second paid advisor before there is a concrete provider request.
- Sending entire conversations or workspaces automatically.
- Building a generic budget ledger for the existing monthly subscription.
