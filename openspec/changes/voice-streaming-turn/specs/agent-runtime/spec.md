## ADDED Requirements

### Requirement: Streaming Chat Endpoint For Voice

The agent-orchestrator SHALL expose a streaming chat interface for voice
consumers that yields assistant text tokens as they are generated via the
LiteLLM gateway. Non-streaming `POST /chat` SHALL remain available and
behaviour-compatible for text tools and batch voice fallback. Voice stream
requests SHALL use the voice-oriented system prompt and short-reply policy
when the session id indicates a voice session.

#### Scenario: SSE tokens for voice session

- **WHEN** a client opens the streaming chat endpoint with a voice session id
  and a non-empty user text
- **THEN** the response is a stream of text token events ending with a
  terminal done event, and model calls go through LiteLLM (not direct engine
  URLs)

#### Scenario: Non-stream chat unchanged

- **WHEN** a client calls non-streaming `POST /chat` with a text session id
- **THEN** the response is a single JSON body with the full assistant text as
  before this change

---

### Requirement: Stream Errors Are Terminal And Explicit

If the upstream LiteLLM stream fails mid-turn, the orchestrator SHALL emit an
explicit error terminal event (or non-2xx for non-SSE modes) and SHALL NOT
silently hang the client.

#### Scenario: Upstream stream failure

- **WHEN** LiteLLM streaming fails after the connection is open
- **THEN** the client receives a terminal error indication and can fall back
  to batch chat
