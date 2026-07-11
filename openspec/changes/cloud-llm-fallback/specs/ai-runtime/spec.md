## MODIFIED Requirements

### Requirement: LiteLLM Gateway Is The Single OpenAI-Compatible Endpoint

The LiteLLM container SHALL bind to `127.0.0.1:4000` and expose OpenAI-compatible + Anthropic-compatible surfaces. Every AI consumer (dev tools, agents, voice pipeline, scripts) SHALL address models by alias through this endpoint. Direct calls to vendor endpoints (Anthropic, OpenAI, Google) are permitted ONLY inside `modules/llm-litellm/` itself, where LiteLLM proxies them under the `-cloud`-suffixed aliases defined by this change. Whether assistant traffic automatically selects a cloud alias SHALL remain outside this change's authority (owned by `0002-assistant-intelligence-routing`); this change only provisions cloud aliases and credentials.

The gateway SHALL serve BOTH sets of aliases from the same endpoint:

- **Local aliases** (backend-routed to Ollama / Lemonade / vLLM): `router-1b`, `intent-3b`, `main-70b`, `coder-fast`, `coder-strong`, `coder-thinking`, `embed-bge`, `vlm-qwen2vl`.
- **Cloud aliases** (routed off-machine via API keys): `main-cloud`, `coder-cloud`, `thinking-cloud`, `gpt4o-cloud`, `gemini-cloud`.

#### Scenario: Consumer sees one endpoint for local and cloud

- **WHEN** a consumer requests `main-70b` and later `main-cloud` from `http://127.0.0.1:4000/v1/chat/completions`
- **THEN** both requests succeed at the same endpoint with the same auth shape; only the resolved backend differs

#### Scenario: Cloud alias resolves when key present

- **WHEN** `main-cloud` is requested and `ANTHROPIC_API_KEY` is set in the LiteLLM container environment
- **THEN** LiteLLM routes the request to `anthropic/claude-sonnet-4-6`

#### Scenario: Cloud alias fails cleanly when key missing

- **WHEN** `main-cloud` is requested and `ANTHROPIC_API_KEY` is not set
- **THEN** LiteLLM returns a well-formed error naming the missing key; local aliases continue to serve normally

## ADDED Requirements

### Requirement: Cloud API Keys Load At Runtime From SOPS-Encrypted Source

Cloud provider API keys (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`) SHALL never be baked into the image. They SHALL be decrypted at runtime by a systemd oneshot (`aipc-decrypt-cloud-keys.service`) from `/etc/aipc/secrets/cloud-llm.yaml` (SOPS-encrypted) using `/etc/aipc/age.key`, written to `/etc/aipc/env.d/llm-litellm/cloud-keys.env` (mode 0600 root:root), and consumed by the LiteLLM quadlet via `EnvironmentFile=`.

The service SHALL use `ConditionPathExists=/etc/aipc/secrets/cloud-llm.yaml` so machines without a cloud key file boot cleanly (the unit is skipped, not failed), and `Before=litellm.service` so the env file exists before the container starts.

#### Scenario: First boot with cloud key present

- **WHEN** the host boots with `/etc/aipc/secrets/cloud-llm.yaml` and `/etc/aipc/age.key` present
- **THEN** `aipc-decrypt-cloud-keys.service` runs before `litellm.service`, writes `/etc/aipc/env.d/llm-litellm/cloud-keys.env` mode 0600, and LiteLLM starts with the cloud env vars populated

#### Scenario: Boot without cloud key file

- **WHEN** the host boots with no `/etc/aipc/secrets/cloud-llm.yaml`
- **THEN** `aipc-decrypt-cloud-keys.service` is skipped via `ConditionPathExists`, `litellm.service` starts normally, and local aliases serve requests

#### Scenario: Cloud key file present but decryption fails

- **WHEN** `/etc/aipc/secrets/cloud-llm.yaml` exists but `/etc/aipc/age.key` is missing or wrong
- **THEN** `aipc-decrypt-cloud-keys.service` exits non-zero with a diagnostic on stderr; `litellm.service` still starts (cloud aliases will fail per the "missing key" scenario, local aliases work)

#### Scenario: Key rotation

- **WHEN** the user re-encrypts `/etc/aipc/secrets/cloud-llm.yaml` with a new provider key and runs `systemctl restart aipc-decrypt-cloud-keys.service litellm.service`
- **THEN** the new key is loaded and cloud aliases resolve against the updated credentials without a reboot

### Requirement: Cloud Model Mappings Are Config-Only

The mapping from cloud alias to specific vendor model ID SHALL live in `modules/llm-litellm/files/etc/aipc/litellm/config.yaml` and be shipped as data (no code changes required to swap `claude-sonnet-4-6` for a newer Anthropic model, or `gpt-4o` for `gpt-4.1`). Updating a mapping SHALL require only editing the config file and rebuilding the image.

The default mappings SHALL be:

- `main-cloud` → `anthropic/claude-sonnet-4-6`
- `coder-cloud` → `anthropic/claude-sonnet-4-6`
- `thinking-cloud` → `anthropic/claude-opus-4-8`
- `gpt4o-cloud` → `openai/gpt-4o`
- `gemini-cloud` → `gemini/gemini-2.5-pro`

#### Scenario: Swap a cloud provider without code changes

- **WHEN** the user edits `main-cloud`'s `model:` line in the LiteLLM config and rebuilds the image
- **THEN** the new mapping takes effect on next `litellm.service` start with no changes to any other module or CLI
