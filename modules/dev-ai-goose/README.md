# dev-ai-goose

Goose CLI (Block's AI agent), configured for LiteLLM and MCP gateway.

## What it does

- Installs Goose via the official installer script (idempotent).
- Creates a config file pointing at the LiteLLM gateway.

## Dependencies

- `llm-litellm` (LiteLLM gateway at `http://127.0.0.1:4000`).

## Consumers

End user via terminal. All model calls route through LiteLLM per CLAUDE.md §7.
