## ADDED Requirements

### Requirement: Lemonade Weights Under Shared Model Root

The `llm-lemonade` module SHALL persist its HuggingFace model cache under the shared `/var/lib/aipc-models` tree (the root `aipc-models-dir.service` resolves to the primary user's `~/aipc-models`), bind-mounting `/var/lib/aipc-models/hf` to the container's `/root/.cache/huggingface`, so that Ollama blobs and Lemonade HF weights share a single root and duplicated/stale weights become visible. Lemonade's non-weight mounts — `cache` (`/root/.cache/lemonade`, lemonade config) and `flm` (`/root/.config/flm`, FLM backend state) — SHALL remain under `/var/lib/aipc-lemonade` and are not part of the shared model root.

#### Scenario: HF cache bind volume points at the shared root

- **WHEN** the `lemonade.service` unit is rendered
- **THEN** its HuggingFace bind volume is `-v /var/lib/aipc-models/hf:/root/.cache/huggingface:Z` and its `ExecStartPre` mkdir creates `/var/lib/aipc-models/hf`

#### Scenario: Non-weight Lemonade mounts are unchanged

- **WHEN** the unit is rendered
- **THEN** the `cache` (`/root/.cache/lemonade`) and `flm` (`/root/.config/flm`) bind volumes still point at `/var/lib/aipc-lemonade/cache` and `/var/lib/aipc-lemonade/flm` respectively

#### Scenario: Ollama weights already share the same root

- **WHEN** both backends store weights on the deployed host
- **THEN** Ollama blobs (`/var/lib/aipc-models/blobs`) and Lemonade HF weights (`/var/lib/aipc-models/hf`) live under the single `/var/lib/aipc-models` tree, so `du`/`ls` of one path accounts for all model weights
