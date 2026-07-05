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

## Build-time vs runtime split

`post-install.sh` is **build-time only**: it runs `systemctl enable
rag-embedder.service` (no `--now`). It does NOT start the service, probe
`/healthz`, or call any client — none of those work at image-build time
(no init, nothing listening on 8201). The original scaffold did all
three and would hang/fail on every rebuild.

rag-embedder needs no host-side runtime init: the container self-manages
model downloads on first start, and the quadlet orders it
`After=ai-rocm.service` / `Requires=ai-rocm.service`. Runtime health is
asserted by `verify.sh` (`systemctl is-active` + `curl /healthz`), which
is the correct place for it.

> **Quadlet deployment gap: resolved.** `quadlet-render-support`
> (2026-07-01) made both renderers COPY `quadlet/` into
> `/etc/containers/systemd/`, so `rag-embedder.service` is present at
> build time. Enablement is still gated on hardware verification, not
> this gap.

## Endpoints

- `http://127.0.0.1:8201/embed` — native endpoint (input: `{"texts": [...]}`).
- `http://127.0.0.1:8201/v1/embeddings` — OpenAI-compatible alias of
  `/embed` (same model, request/response reshaped to the OpenAI
  embeddings schema). Required so LiteLLM's `openai/` provider can
  reach it via the gateway's `embed-bge` alias
  (`modules/llm-litellm`) — LiteLLM's openai-compatible client always
  calls `{api_base}/embeddings`, it has no way to target `/embed`
  directly.
- `http://127.0.0.1:8201/rerank`
- `http://127.0.0.1:8201/healthz`

> The actual FastAPI/whatever service behind this quadlet
> (`docker.io/aipc/rag-embedder:latest`) has no source in this repo yet
> — it's a placeholder image reference. Building and publishing it is
> real, separate work (pick a serving framework — TEI, vLLM, or a thin
> custom FastAPI wrapper over FlagEmbedding — and implement both the
> native and OpenAI-compatible routes above) and isn't done as part of
> this pass.

## Dependencies

- `llm-litellm` (the `embed-bge` alias points at this service for
  callers that prefer the LiteLLM gateway).
- `ai-rocm` (GPU device nodes).
