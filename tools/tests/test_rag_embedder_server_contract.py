from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


def _load_server_module(monkeypatch, encode_fn):
    class FakeSentenceTransformer:
        def __init__(self, name: str) -> None:
            self.name = name

        def encode(self, texts, **kwargs):
            return encode_fn(texts)

    st_module = types.SimpleNamespace(SentenceTransformer=FakeSentenceTransformer)
    fastapi = types.SimpleNamespace(FastAPI=lambda **kwargs: _FakeApp())
    pydantic = types.SimpleNamespace(BaseModel=_BaseModel)
    monkeypatch.setitem(sys.modules, "sentence_transformers", st_module)
    monkeypatch.setitem(sys.modules, "fastapi", fastapi)
    monkeypatch.setitem(sys.modules, "pydantic", pydantic)

    p = (
        Path(__file__).resolve().parents[2]
        / "modules/rag-embedder/files/usr/lib/aipc-rag-embedder/aipc_rag_embedder/server.py"
    )
    spec = importlib.util.spec_from_file_location("aipc_rag_embedder_server_for_test", p)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class _FakeApp:
    def get(self, path):
        return lambda fn: fn

    def post(self, path):
        return lambda fn: fn


class _BaseModel:
    def __init__(self, **kwargs):
        for name, default in getattr(self, "__class__", type(self)).__dict__.items():
            if name.startswith("_") or callable(default):
                continue
            setattr(self, name, kwargs.pop(name, default))
        for name, value in kwargs.items():
            setattr(self, name, value)


def test_embed_native_endpoint_returns_vectors_for_each_text(monkeypatch):
    server = _load_server_module(monkeypatch, lambda texts: [[0.1, 0.2] for _ in texts])
    req = server.EmbedRequest(texts=["a", "b"])

    result = server.embed(req)

    assert result == {"embeddings": [[0.1, 0.2], [0.1, 0.2]]}


def test_openai_compat_embeddings_accepts_string_input(monkeypatch):
    server = _load_server_module(monkeypatch, lambda texts: [[1.0, 2.0, 3.0] for _ in texts])
    req = server.OpenAIEmbeddingsRequest(model="embed-bge", input="hello")

    result = server.openai_embeddings(req)

    assert result["data"] == [{"object": "embedding", "index": 0, "embedding": [1.0, 2.0, 3.0]}]
    assert result["model"] == "embed-bge"
    assert result["object"] == "list"


def test_openai_compat_embeddings_accepts_list_input(monkeypatch):
    server = _load_server_module(monkeypatch, lambda texts: [[1.0], [2.0]])
    req = server.OpenAIEmbeddingsRequest(model="embed-bge", input=["a", "b"])

    result = server.openai_embeddings(req)

    assert [d["index"] for d in result["data"]] == [0, 1]
    assert [d["embedding"] for d in result["data"]] == [[1.0], [2.0]]
