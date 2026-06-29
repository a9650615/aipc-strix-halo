# dev-ai-opencode

OpenCode CLI — terminal AI coding tool, configured for LiteLLM.

## Install

```
distrobox enter node -- npm install -g opencode-ai
```

## Configuration

Skel config at `/etc/skel/.config/opencode/config.json` points at LiteLLM.

## Dependencies

- `llm-litellm` (gateway at `http://127.0.0.1:4000`).
- `dev-distrobox-templates` (Node template).
