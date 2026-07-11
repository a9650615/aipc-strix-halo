# llm-litellm

Runs the LiteLLM proxy as a Podman quadlet. Single entry point for every AI
consumer in the system (Continue.dev, Cline, Aider, Goose, voice pipeline,
agent tools, scripts).

## What it does

- Accepts OpenAI-compatible requests on a localhost port.
- Routes by logical model name to Lemonade, Ollama, or vLLM backends.
- Provides observability (request logs, cost tracking) and rate limiting.

## Model namespace (public API surface)

`resident-small`, `coder-agentic`, `ornith-35b`, `assistant-gemma`,
`qwythos-9b`, `vlm-*`, plus the cloud aliases (`main-cloud`, `coder-cloud`,
`thinking-cloud`, `gpt4o-cloud`, `gemini-cloud`) — see `llm-models`.
`qwen35-122b-q3` was retired 2026-07-11 (weights deleted; too heavy for
comfortable UMA use; avoid dual-backend giants).

Adding a new logical model = a LiteLLM config entry, nothing else.

## Container image pin

`quadlet/litellm.container` pins `ghcr.io/berriai/litellm` to a digest
(currently v1.89.4 stable). Floating tags like `:main-latest` are forbidden —
the image is rebuilt on every `bootc switch`, so a tag drift would silently
change behaviour across hosts. Re-verified 2026-07-02 via
`docker buildx imagetools inspect ghcr.io/berriai/litellm:v1.89.4` — the
manifest-list digest matches the pinned `sha256:afdc3cc3…` exactly.

To update the pin:

1. Pick a target version on the [GitHub packages page](https://github.com/orgs/berriai/packages/container/litellm/versions).
2. Copy the digest (`sha256:…`) for the chosen version.
3. Replace the `Image=` line in `quadlet/litellm.container`.
4. Re-render both targets and confirm parity (see `AGENTS.md §4`).

## Timeouts

`config.yaml` sets `router_settings.timeout: 600` and
`litellm_settings.request_timeout: 600` — both are per-request ceilings, not
idle-backend eviction. `cooldown_time: 60` / `allowed_fails: 3` only trip on
failures, not idleness.

Confirmed 2026-07-02 against the pinned tag (v1.89.4): LiteLLM's proxy has
**no** native "unload backend after N minutes of zero traffic" key. Checked
both `litellm/types/router.py::RouterConfig` (the full `router_settings:`
schema — `redis_*`, `cache_*`, `client_ttl`, `num_retries`, `timeout`,
`allowed_fails`, `retry_after`, `routing_strategy`, `model_group_alias`, no
idle field) and `litellm/proxy/_types.py` general settings (only a DB
connection idle timeout, unrelated to model backends). LiteLLM is a
stateless HTTP proxy — it has no handle on the vLLM process's lifecycle, so
it structurally cannot evict it.

Idle eviction must be configured on the backend itself: vLLM's
`--timeout-keep-alive` doesn't stop the process either, so the real fix is a
systemd-level idle-shutdown wrapper (timer or `ExecStopPost`) in
`modules/llm-vllm`'s own quadlet — tracked as a gap, not yet implemented.
Lemonade's model unload policy and Ollama's `OLLAMA_KEEP_ALIVE` are the
equivalent knobs for those two backends. See the `# ponytail:` comment next
to `router_settings` in `config.yaml` for the inline pointer.

## Unit placement

`quadlet/litellm.container` is placed by the bootc/ansible renderer into
`/etc/containers/systemd/`; podman's generator starts `litellm.service` at
boot. `post-install.sh` only stages `config.yaml` + the endpoint file — it no
longer hand-copies the unit or runs `systemctl --user`.

## Dependencies

- `llm-lemonade` (NPU + iGPU/Vulkan backend for `resident-small`,
  `coder-agentic`, `ornith-35b` — primary local backend as of 2026-07-05;
  also bundles a vLLM/ROCm backend, not currently wired to a registered
  alias — see its README).
- `llm-ollama` (iGPU backend; installed/enabled but currently idle — no
  aliases point to it, see `llm-ollama`'s README).
- `llm-vllm` (superseded by `llm-lemonade`'s vLLM backend, kept `.disabled`).
- `secrets-sops` (API keys for any cloud fallback routes).

## Consumers

Every AI consumer **must** point at the LiteLLM endpoint declared in
`env/endpoint`. Direct calls to Ollama/Lemonade/vLLM are forbidden outside
their own modules. See `CLAUDE.md §7`.
