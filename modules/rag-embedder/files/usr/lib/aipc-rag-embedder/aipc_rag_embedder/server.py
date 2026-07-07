"""FastAPI wrapper around bge-m3 embeddings (rag-embedder, Phase 2).

The upstream quadlet's `docker.io/aipc/rag-embedder:latest` has no source
anywhere -- a placeholder image reference, same root-cause class as
memory-mem0/voice-stt-sensevoice/dev-ai-mcp-dev-servers/agent-browser
(fictitious or wrong-arch prebuilt image). Replaced with a native systemd +
venv service, same pattern as those modules.

# ponytail: CPU-only via sentence-transformers, no iGPU/Lemonade wiring yet.
# D4's "served via Lemonade ONNX on iGPU" is the eventual target; this gets
# embed-bge actually answering requests today. Swap the encode() body for a
# Lemonade/ROCm-backed model once that runtime is wired for embeddings.
"""

import os

from fastapi import FastAPI
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

MODEL_NAME = os.environ.get("AIPC_EMBED_MODEL", "BAAI/bge-m3")

app = FastAPI(title="aipc-rag-embedder")
_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model


class EmbedRequest(BaseModel):
    texts: list[str]


class OpenAIEmbeddingsRequest(BaseModel):
    model: str
    input: str | list[str]


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


def _to_floats(vector) -> list[float]:
    # ponytail: sentence-transformers returns numpy.float32, which FastAPI's
    # pydantic serializer can't JSON-encode directly -- cast to native float.
    return [float(x) for x in vector]


@app.post("/embed")
def embed(req: EmbedRequest) -> dict:
    vectors = _get_model().encode(req.texts, normalize_embeddings=True)
    return {"embeddings": [_to_floats(v) for v in vectors]}


@app.post("/v1/embeddings")
def openai_embeddings(req: OpenAIEmbeddingsRequest) -> dict:
    texts = [req.input] if isinstance(req.input, str) else req.input
    vectors = _get_model().encode(texts, normalize_embeddings=True)
    return {
        "object": "list",
        "model": req.model,
        "data": [
            {"object": "embedding", "index": i, "embedding": _to_floats(v)}
            for i, v in enumerate(vectors)
        ],
    }
