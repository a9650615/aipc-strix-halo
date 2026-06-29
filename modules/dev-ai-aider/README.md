# dev-ai-aider

Aider CLI — AI pair programming in the terminal. Runs via pipx on the host
or inside the Python distrobox template.

## What it does

- Installs `aider-chat` via pipx (idempotent).
- Creates `~/.aider.conf.yml` pointing at the LiteLLM gateway.

## Dependencies

- `llm-litellm` (LiteLLM gateway at `http://127.0.0.1:4000`).
- `dev-distrobox-templates` (Python template, optional — host pipx preferred).

## Consumers

End user via terminal. All model calls route through LiteLLM per CLAUDE.md §7.
