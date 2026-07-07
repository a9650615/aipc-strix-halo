# rag-embedder

HTTP service hosting `bge-m3` (embeddings) so LiteLLM's `embed-bge` alias
resolves to a real backend. mem0 (memory-mem0) and rag-ingest both depend
on this being reachable at `http://127.0.0.1:8201`.

## Design decisions

- **D4** — bge-m3 and the reranker were designed to be served from one
  process, sharing a model cache and iGPU context.

## What it does — native systemd + venv, not a container

**Root-cause finding, 2026-07-07**: the quadlet's
`docker.io/aipc/rag-embedder:latest` never had a real source anywhere —
same root-cause class as `memory-mem0` (fictitious/placeholder prebuilt
image). Fixed the same way: replaced the container with a native systemd
service (`aipc-rag-embedder.service`) running a small FastAPI wrapper
(`aipc_rag_embedder/server.py`) around `sentence-transformers` loading
`BAAI/bge-m3`, in a venv at `/usr/lib/aipc-rag-embedder/venv`.

# ponytail: CPU-only for now, no iGPU/Lemonade wiring. D4's "served via
# Lemonade ONNX on iGPU" is the real target once Lemonade exposes an
# embeddings API; this unblocks embed-bge/mem0 today. Swap server.py's
# model backend when that lands — the HTTP contract below doesn't change.

**Not implemented in this pass**: `bge-reranker-v2-m3` and the `/rerank`
endpoint. Nothing in the current mem0/RAG write path calls it yet;
building it is separate follow-up work, tracked in
`openspec/changes/phase-2-memory/tasks.md` group 4.

## Build-time vs runtime split

`post-install.sh` is **build-time only**: builds the venv, installs pinned
requirements, creates `/var/lib/aipc-rag-embedder/hf-cache`, relabels the
venv entrypoints for the systemd SELinux transition, and `systemctl enable
aipc-rag-embedder.service` (no `--now`). Nothing is probed or started at
image-build time.

`BAAI/bge-m3` weights are a runtime/firstboot concern: pre-stage them under
`HF_HOME` before the service is useful. The unit sets `HF_HUB_OFFLINE=1` and
`TRANSFORMERS_OFFLINE=1`, so runtime never phones HuggingFace once weights
exist.

## Verification (2026-07-07, updated 2026-07-08)

Real functional testing on the dev host first, then hardware verification on
the physical Strix Halo AI PC:

- Real venv built, real `sentence-transformers`/`torch` installed, real
  `BAAI/bge-m3` weights downloaded and loaded.
- Ran the real FastAPI app over real HTTP (`uvicorn ... --port 8201`):
  `GET /healthz` → `200`.
- `POST /v1/embeddings` with `{"model":"embed-bge","input":"..."}` →
  real 1024-dim vector, matching the dimension `mem0_memories` and
  `rag_chunks` already assume.
- Confirmed LiteLLM's `embed-bge` alias resolves through this service
  end-to-end (gateway → `openai` provider → `http://127.0.0.1:8201/v1/embeddings`).
- **2026-07-08 hardware verification**: the same service was started on the
  physical AI PC, with bge-m3 pre-staged under `HF_HOME`, and LiteLLM's
  `embed-bge` path returned real embeddings through `127.0.0.1:4000`.

Two hardware-only bugs were found and fixed:

1. The systemd service executed the venv's `python3`/`uvicorn` while the
   entrypoints were labeled `etc_t`/`lib_t`, so the process stayed in
   `init_t`. That denied both HuggingFace egress and oneDNN JIT mmap-exec,
   surfacing as `Permission denied` and `RuntimeError: could not create a
   primitive`. Fix: relabel `…/venv/bin` to `bin_t` in `post-install.sh`.
2. bge-m3 was not staged, so first request tried a runtime HF fetch. Fix:
   pre-stage weights and force offline mode in the unit.

**Net verification tier**: hardware-verified 2026-07-08 on the physical
Strix Halo AI PC. Module is enabled (`.disabled` removed).

## Endpoints

- `http://127.0.0.1:8201/healthz`
- `http://127.0.0.1:8201/embed` — native (`{"texts": [...]}` ->
  `{"embeddings": [[...], ...]}`)
- `http://127.0.0.1:8201/v1/embeddings` — OpenAI-compatible, what
  LiteLLM's `openai/` provider actually calls for the `embed-bge` alias.
- `/rerank` — not implemented yet (see above).

## Dependencies

- `llm-litellm` (the `embed-bge` alias points at this service).
