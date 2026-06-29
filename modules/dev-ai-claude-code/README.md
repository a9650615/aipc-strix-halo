# dev-ai-claude-code

Claude Code CLI — Anthropic's terminal coding agent, routed through LiteLLM.

## Install

```
distrobox enter node -- npm install -g @anthropic-ai/claude-code
```

User must run `claude login` post-install.

## Environment

`env/anthropic-base-url` sets `ANTHROPIC_BASE_URL=http://127.0.0.1:4000`.

## Dependencies

- `llm-litellm` (Anthropic-compatible route).
- `dev-distrobox-templates` (Node template).
