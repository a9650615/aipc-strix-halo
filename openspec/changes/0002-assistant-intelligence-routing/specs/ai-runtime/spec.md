# ai-runtime Specification Delta

## MODIFIED Requirements

### Requirement: LiteLLM Gateway Is The Single OpenAI-Compatible Endpoint

The LiteLLM container SHALL bind to `127.0.0.1:4000` and SHALL remain the
single model API endpoint used by assistant consumers. Local and metered API
models SHALL be addressed through stable role/capability aliases whose concrete
provider/model mappings are configuration. Subscription CLI workers and
optional agent proxies are agent adapters, not model API bypasses: they SHALL
be invoked only by the agent executor under an assistant RouteDecision and
ExecutionGrant.

The gateway and model manifest SHALL be generated from or validated against one
canonical capability registry so alias, locality, billing class, modality,
tool support, context, and backend mappings cannot silently drift. Provider-
specific aliases MAY remain available for diagnostics and explicit overrides,
but SHALL NOT be the public routing contract.

This requirement supersedes `cloud-llm-fallback`'s manual-only policy for
assistant traffic only: policy-approved automatic escalation is permitted.
Explicit alias selection remains deterministic, credentials remain optional,
and missing credentials remove a provider from the candidate set rather than
causing repeated fallback attempts.

#### Scenario: Assistant resolves a role without backend knowledge

- **WHEN** the router selects a role/capability tier for a task
- **THEN** the ai-runtime registry resolves an eligible configured backend
  without the router containing a vendor URL or concrete model ID

#### Scenario: Missing cloud credentials

- **WHEN** a metered backend has no usable runtime credential
- **THEN** it SHALL be marked ineligible before execution, local providers SHALL
  continue operating, and an error SHALL be shown only when the user explicitly
  requested that backend or no permitted alternative exists

#### Scenario: Registry drift

- **WHEN** a role alias, backend mapping, or capability differs between the
  canonical registry, generated LiteLLM config, and model manifest
- **THEN** static verification SHALL fail before image rendering succeeds

## ADDED Requirements

### Requirement: Provider Billing And Capability Metadata Are Runtime Inputs

Every routable model/provider SHALL expose locality, billing class
(`local` | `subscription` | `metered`), supported modalities/tools/structured
output, context limit, health, and a freshness-bounded quota/budget state. A
missing or stale quota SHALL be represented as `unknown`, never unlimited.

#### Scenario: Unknown subscription quota

- **WHEN** an authenticated subscription CLI is healthy but no supported quota
  source is available
- **THEN** the router MAY use it only under the configured unknown-quota policy
  and SHALL record `quota=unknown`
