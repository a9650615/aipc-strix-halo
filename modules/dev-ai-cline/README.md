# dev-ai-cline

Cline VSCode extension, pre-configured for the LiteLLM gateway.

## What it does

- Installs the `saoudrizwan.claude-dev` (Cline) VSCode extension (idempotent).
- Ships skel config at `/etc/skel/.config/cline/config.yaml` pointing at LiteLLM.

## Dependencies

- `dev-editors` (VSCode must be available).
- `llm-litellm` (LiteLLM gateway at `http://127.0.0.1:4000`).

## Consumers

End user via VSCode. All model calls route through LiteLLM per CLAUDE.md §7.
