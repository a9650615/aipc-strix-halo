# rag-embedder

HTTP service hosting `bge-m3` (embedding) and `bge-reranker-v2-m3`
(reranking) on the iGPU via the Lemonade ONNX runtime. Single quadlet,
shared model cache.

## Design decisions

- **D4** — bge-m3 and the reranker are served from the same process so
  both models share a single cache and a single iGPU context.

## What it does

- Runs the embedder service as a podman quadlet bound to
  `127.0.0.1:8201`.
- Exposes `/embed` and `/rerank` over HTTP.
- Mounts the shared model cache at `/var/lib/aipc-models`.
- Requests GPU access via `/dev/kfd` + `/dev/dri`.

## Endpoints

- `http://127.0.0.1:8201/embed`
- `http://127.0.0.1:8201/rerank`
- `http://127.0.0.1:8201/healthz`

## Dependencies

- `llm-litellm` (the `embed-bge` alias points at this service for
  callers that prefer the LiteLLM gateway).
- `ai-rocm` (GPU device nodes).
