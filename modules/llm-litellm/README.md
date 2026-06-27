# llm-litellm

Runs the LiteLLM proxy as a Podman quadlet. Single entry point for every AI
consumer in the system (Continue.dev, Cline, Aider, Goose, voice pipeline,
agent tools, scripts).

## What it does

- Accepts OpenAI-compatible requests on a localhost port.
- Routes by logical model name to Ollama, Lemonade, or vLLM backends.
- Provides observability (request logs, cost tracking) and rate limiting.

## Model namespace (public API surface)

`router-1b`, `intent-3b`, `main-70b`, `coder-fast`, `coder-strong`,
`coder-thinking`, `embed-bge`, `vlm-qwen2vl`.

Adding a new logical model = a LiteLLM config entry, nothing else.

## Dependencies

- `llm-ollama` (iGPU backend for most models).
- `llm-lemonade` (NPU backend for `intent-3b`, `embed-bge`).
- `llm-vllm` (optional, for high-throughput serving).
- `secrets-sops` (API keys for any cloud fallback routes).

## Consumers

Every AI consumer **must** point at the LiteLLM endpoint declared in
`env/endpoint`. Direct calls to Ollama/Lemonade/vLLM are forbidden outside
their own modules. See `CLAUDE.md §7`.
