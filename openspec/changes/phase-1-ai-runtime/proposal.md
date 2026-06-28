## Why

Phase 0 proved the hardware: 128 GB GTT is visible to ROCm, the XDNA NPU
enumerates, and a 70B model loads without OOM. Phase 1 layers the inference
stack on top so every downstream consumer (voice pipeline, agent framework,
dev tooling) has a stable, model-name-addressed LLM gateway to call.

Four of the seven Phase 1 modules were added to `modules/` without a prior
OpenSpec change. This change retroactively specifies all seven, legalises the
four that exist, and schedules the three that are still missing.

## What Changes

- **New capability `ai-runtime`** covering all seven Phase 1 modules as one
  coherent inference layer.
- Four modules already committed to `modules/` (`llm-litellm`, `llm-lemonade`,
  `llm-ollama`, `llm-vllm`) are brought under spec; gaps found during this
  review become tasks.
- Three modules still absent from `modules/` (`ai-rocm`, `ai-xdna`,
  `llm-models`) are specified and scheduled for implementation.
- `aipc models sync` CLI subcommand is defined; it reads `models.yaml` and
  pulls any missing weights into `/var/lib/aipc-models`.
- `aipc doctor` gains checks for all seven ai-runtime modules, including a
  live `GET /v1/models` against the LiteLLM gateway.

## Capabilities

### New Capabilities

- `ai-runtime`: Seven-module inference layer — ROCm driver stack, XDNA NPU
  userspace, Lemonade SDK service (NPU), Ollama service (iGPU), LiteLLM
  gateway, vLLM on-demand backend, and the models manifest. Together they form
  the single OpenAI-compatible endpoint consumed by all host AI software.

### Modified Capabilities

- `system-foundation`: No requirement changes. Phase 0's unified-memory and
  BTRFS-subvolume decisions are load-bearing prerequisites here (Q8c, Phase 0
  D-something) but their specs are unchanged.

## Impact

- **`modules/`**: Four existing modules receive spec-driven gap fixes (see
  tasks group 1); three new modules are added (tasks group 2).
- **`tools/aipc`**: New `models` subcommand added (tasks group 3).
- **`tools/aipc doctor`**: Extended to cover ai-runtime modules (tasks group 4).
- **`targets/bootc/Containerfile` + `targets/ansible/site.yml`**: Rendered
  outputs grow by seven modules; no divergence expected.
- **Model weights**: Downloaded at first-boot via `aipc models sync`, not
  baked into the image; BTRFS subvolume at `/var/lib/aipc-models` (established
  in Phase 0) is the target.
- **Downstream consumers**: Any caller that previously reached Ollama or
  Lemonade directly MUST be updated to route through the LiteLLM gateway on
  `http://127.0.0.1:4000`.
