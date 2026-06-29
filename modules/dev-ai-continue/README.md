# dev-ai-continue

Continue.dev VSCode extension, pre-configured to use the LiteLLM gateway as
its LLM backend.

## What it does

- Installs the `Continue.continue` VSCode extension (idempotent).
- Drops a default `.continue/config.yaml` pointing at the LiteLLM endpoint.

## Dependencies

- `dev-editors` (VSCode must be available).
- `llm-litellm` (LiteLLM gateway at `http://127.0.0.1:4000`).

## Consumers

End user via VSCode. All model calls route through LiteLLM per CLAUDE.md §7.
