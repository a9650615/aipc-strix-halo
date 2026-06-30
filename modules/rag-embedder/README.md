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

> **Quadlet deployment gap (pre-existing, blocks enablement).** The
> bootc renderer COPYs `files/`, `modprobe.d/`, `env/` but does NOT
> install `quadlet/`. This module's `post-install.sh` enables
> `rag-embedder.service` without installing the quadlet file, so the unit is
> absent at build — `systemctl enable` would fail if `.disabled` were
> removed today. Same gap affects `db-postgres`, `llm-ollama`,
> `memory-mem0`, `rag-ingest`. Resolving it (install target +
> `.service`-vs-`.container` naming) is a cross-cutting decision that
> needs an OpenSpec change, not a per-module patch.

## Endpoints

- `http://127.0.0.1:8201/embed`
- `http://127.0.0.1:8201/rerank`
- `http://127.0.0.1:8201/healthz`

## Dependencies

- `llm-litellm` (the `embed-bge` alias points at this service for
  callers that prefer the LiteLLM gateway).
- `ai-rocm` (GPU device nodes).
