## Why

Local models cover most workloads, but not all:

- **Capacity**: a 70B model saturates the unified memory pool under heavy concurrent load; offloading a burst to cloud frees GTT for local inference.
- **Specific capabilities**: Claude reasoning (extended thinking), GPT-4o multimodal, Gemini long-context — capabilities no local model currently matches at acceptable quality.
- **Hardware maintenance**: when the APU is thermally throttled or the iGPU driver is mid-update, a cloud route keeps the user productive.

The LiteLLM gateway already owns model routing. Adding cloud backends is a config extension, not an architectural change.

## What Changes

- **LiteLLM config**: five new model entries with `-cloud` suffix routed to Anthropic, OpenAI, and Google.
- **Models manifest**: five new alias entries in `models.yaml` with `backend: cloud`.
- **Secrets**: `secrets/cloud-llm.yaml` (SOPS-encrypted) stores `anthropic_api_key`, `openai_api_key`, `gemini_api_key`.
- **Key delivery**: `secrets-sops` post-install decrypts to `/etc/aipc/env.d/llm-litellm/cloud-keys.env`; the LiteLLM quadlet loads it via `EnvironmentFile`.
- **Docs**: `docs/secrets-setup.md` gains a section on provisioning cloud API keys.

## Capabilities

### New Capabilities

None. Cloud fallback extends the existing `ai-runtime` capability.

### Modified Capabilities

- `ai-runtime`: LiteLLM gains five cloud-routed model aliases. The gateway remains the single endpoint; consumers see no difference beyond the model name they request.

## Non-Goals

- Automatic fallback on local failure — switching is manual by design.
- Load balancing across cloud and local backends.
- Billing alerts or spend caps — cloud providers handle this.
- Cloud models for latency-sensitive paths (voice wake-word, STT) — those stay local-only.
- Any change to the LiteLLM gateway address or consumer routing contract.

## Impact

- **`modules/llm-litellm/`**: `config.yaml` gains five entries; `quadlet/litellm.service` gains `EnvironmentFile`.
- **`modules/llm-models/`**: `models.yaml` gains five entries.
- **`modules/secrets-sops/`**: `post-install.sh` gains cloud-keys.env generation.
- **`secrets/`**: new `cloud-llm.yaml.example` template.
- **`docs/secrets-setup.md`**: new section for cloud key provisioning.
- **No new modules, no new containers, no new ports.**
