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

## Container image pin

`quadlet/litellm.service` pins `ghcr.io/berriai/litellm` to a digest
(currently v1.89.4 stable). Floating tags like `:main-latest` are forbidden —
the image is rebuilt on every `bootc switch`, so a tag drift would silently
change behaviour across hosts.

To update the pin:

1. Pick a target version on the [GitHub packages page](https://github.com/orgs/berriai/packages/container/litellm/versions).
2. Copy the digest (`sha256:…`) for the chosen version.
3. Replace the `Image=` line in `quadlet/litellm.service`.
4. Re-render both targets and confirm parity (see `AGENTS.md §4`).

## Timeouts

`config.yaml` sets `router_settings.timeout: 600` and
`litellm_settings.request_timeout: 600` — both are per-request ceilings, not
idle-backend eviction. LiteLLM's proxy has no native "unload after N seconds
of zero traffic" key; backend idle eviction must be configured on the backend
itself (vLLM's `--timeout-keep-alive`, Lemonade's model unload policy,
Ollama's `OLLAMA_KEEP_ALIVE`). `cooldown_time: 60` / `allowed_fails: 3` only
trip on failures, not idleness.

## Dependencies

- `llm-ollama` (iGPU backend for most models).
- `llm-lemonade` (NPU backend for `intent-3b`, `embed-bge`).
- `llm-vllm` (optional, for high-throughput serving).
- `secrets-sops` (API keys for any cloud fallback routes).

## Consumers

Every AI consumer **must** point at the LiteLLM endpoint declared in
`env/endpoint`. Direct calls to Ollama/Lemonade/vLLM are forbidden outside
their own modules. See `CLAUDE.md §7`.
