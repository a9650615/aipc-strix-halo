# cloud-llm-fallback

Cloud LLM fallback: Anthropic, OpenAI, and Google models routed through the existing LiteLLM gateway via `-cloud` suffixed aliases. SOPS-encrypted API keys.

**Routing note (2026-07-10):** Assistant traffic automatic escalation is owned by
`0002-assistant-intelligence-routing` (currently paid-off / subscription deferred).
This change only **provisions** cloud aliases and credentials. See `STATUS.md`.
