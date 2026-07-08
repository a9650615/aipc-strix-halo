# Why: Model Weights Are Scattered Across Two Stores

Model weights currently live in **two independent stores** that nothing keeps in
sync:

- Ollama: `/var/lib/aipc-models` (content-addressed `blobs/` + `manifests/`),
  symlinked to the primary user's `~/aipc-models` by `aipc-models-dir.service`.
- Lemonade: `/var/lib/aipc-lemonade/huggingface` (a separate HuggingFace hub
  cache, mounted into the Lemonade container at `/root/.cache/huggingface`).

Because the two backends never share a root, the same model gets downloaded
into each independently, and nothing garbage-collects across them. This was
hardware-observed 2026-07-09 during a disk-pressure cleanup: the same
`Qwen3.5-122B` model existed as **three** copies on one machine — a 76G Ollama
blob, a 93G standalone GGUF in `~/models`, and a ~54G stale copy still in the
Lemonade HF cache long after it had been moved to Ollama (2026-07-07). ~141G
was reclaimable, most of it duplicated/stale weight that a single shared root
would have made visible and avoidable.

A single model root makes the store auditable (`du`/`ls` one tree), lets
`aipc models` reason about on-disk status against one location, and removes
the "which backend owns which copy" ambiguity that let 54G of dead weight sit
unnoticed.
