# dev-ai-cline

Cline VSCode extension, pre-configured for the LiteLLM gateway.

## What it does

- Ships skel config at `/etc/skel/.config/cline/config.yaml` pointing Cline at the LiteLLM gateway (`http://127.0.0.1:4000`).
- The Cline VSCode extension (`saoudrizwan.claude-dev`) is installed at runtime by the user (first VSCode launch, or via `code --install-extension saoudrizwan.claude-dev`).

## Dependencies

- `dev-editors` (VSCode must be available).
- `llm-litellm` (LiteLLM gateway at `http://127.0.0.1:4000`).

## Build vs Runtime

- **Build-time**: Ships the LiteLLM gateway config to `/etc/skel/.config/cline/config.yaml`.
- **Runtime**: User installs the Cline extension via VSCode marketplace (`code --install-extension saoudrizwan.claude-dev`). The extension then reads the shipped config and routes all API calls through the LiteLLM gateway.

## Consumers

End user via VSCode. All model calls route through LiteLLM per CLAUDE.md §7.
