## MODIFIED Requirements

### Requirement: Vision Alias Uses Current-Generation OCR/Grounding Model

The runtime SHALL provide a `vlm-screen` alias backed by
`Qwen3-VL-8B-Instruct` (official Qwen GGUF), replacing the prior
Qwen2.5-VL-7B community re-quant, for screen-description and OCR use via
`agent-screen-control`.

#### Scenario: vlm-screen alias is registered in both the model registry and the router

- **WHEN** `llm-litellm` renders its router config from
  `modules/llm-models/files/etc/aipc/models/models.yaml`
- **THEN** a `vlm-screen` alias exists in both files, pointing at the same
  Lemonade-registered model id

### Requirement: Compact Alias Uses Long-Context Hybrid-Attention Model

The runtime SHALL provide a `coder-compact` alias backed by
`Qwen3.5-4B` (Unsloth `UD-Q4_K_XL` GGUF), replacing the prior Gemma-4-E2B
QAT quant, with a `262144`-token context window reflected in both the model
registry and the router's `max_input_tokens`.

#### Scenario: coder-compact context window matches the model card

- **WHEN** a request against `coder-compact` approaches the router's
  configured `max_input_tokens`
- **THEN** that limit is `262144`, matching the loaded model's native
  context window

### Requirement: Assistant Alias Uses MTP Speculative Decoding, Single-Stream

The runtime SHALL load `assistant-gemma` with its paired MTP draft
checkpoint (`mtp-gemma-4-26B-A4B-it.gguf`) for speculative decoding. Because
llama.cpp's MTP support currently requires a single parallel slot, this
alias SHALL be loaded with `-np 1` (down from the previous `-np 4`) whenever
the draft checkpoint is attached.

#### Scenario: assistant-gemma serves through a single slot when MTP is active

- **WHEN** `assistant-gemma` is loaded with its `draft` checkpoint attached
- **THEN** the load recipe passes `-np 1 -kvu` and a `--spec-type draft-mtp`
  argument, and only one request is served at a time by this alias's
  `llama-server` process

### Requirement: Ornith Alias Defaults to the Decensored Build

The runtime SHALL provide `ornith-35b` backed by
`llmfan46/Ornith-1.0-35B-uncensored-heretic-GGUF` (Heretic-decensored
quant of the same base model), replacing the prior censored upstream build.
This is not a permanent promotion until structured `tool_calls` and
multi-turn tool loops are hardware-verified on this exact quant, matching
the verification bar already applied to `coder-agentic`'s decensored swap.
The alias SHALL carry `idle_unload_after_s: 900`.

#### Scenario: ornith-35b idle-releases after 900 seconds

- **WHEN** `ornith-35b` has been loaded and idle for 900 seconds with no
  intervening request
- **THEN** the existing idle-release policy (see the
  `lemonade-compact-idle-unload` capability) unloads it, the same mechanism
  already governing `coder-compact`

#### Scenario: ornith-35b swap is not trusted as default until tool-calls are re-verified

- **WHEN** the decensored `ornith-35b` build is registered but multi-turn
  structured `tool_calls` have not yet been hardware-verified on this exact
  quant
- **THEN** the swap is documented as provisional, following the same
  caveat pattern already recorded for `coder-agentic`
