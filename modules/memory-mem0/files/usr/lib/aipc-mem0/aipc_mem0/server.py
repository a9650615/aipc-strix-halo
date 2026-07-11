"""FastAPI wrapper around mem0's Memory class (memory-mem0, Phase 2).

The upstream `mem0/mem0:latest` image referenced by this module's original
quadlet does not exist on Docker Hub (confirmed via `skopeo inspect`:
"requested access to the resource is denied"); the real published image,
`mem0/mem0-api-server`, only ships arm64/unknown-arch variants -- no amd64,
so it cannot run on this hardware either. Same root cause class as
voice-stt-sensevoice/dev-ai-mcp-dev-servers/agent-browser (fictitious or
wrong-arch prebuilt image): replaced with a native systemd + venv service
wrapping the real `mem0ai` PyPI package directly, matching those modules'
precedent.

Every LLM/embedding call goes through the LiteLLM gateway (CLAUDE.md §7) --
mem0's own `litellm` provider is the in-process litellm SDK (makes its own
direct calls to backends), not this gateway, so the `openai` provider with
a custom `openai_base_url` is used instead, same pattern as agent-orchestrator's
`ChatLiteLLM(..., custom_llm_provider="openai")`.
"""

import os

from fastapi import FastAPI
from mem0 import Memory
from pydantic import BaseModel

LITELLM_BASE_URL = "http://127.0.0.1:4000"
POSTGRES_CONNECTION_STRING = os.environ.get(
    "AIPC_MEM0_PG_URL", "postgresql://postgres@127.0.0.1:5432/aipc"
)

CONFIG = {
    "vector_store": {
        "provider": "pgvector",
        "config": {
            "connection_string": POSTGRES_CONNECTION_STRING,
            "collection_name": "mem0_memories",
            "embedding_model_dims": 1024,  # bge-m3 dense output dim
        },
    },
    "llm": {
        "provider": "openai",
        "config": {
            "model": "resident-small",
            "openai_base_url": LITELLM_BASE_URL,
            "api_key": "aipc-local",
        },
    },
    "embedder": {
        "provider": "openai",
        "config": {
            "model": "embed-bge",
            "embedding_dims": 1024,
            "openai_base_url": LITELLM_BASE_URL,
            "api_key": "aipc-local",
        },
    },
    "history_db_path": "/var/lib/aipc-mem0/history.db",
}

app = FastAPI(title="aipc-mem0")
_memory: Memory | None = None


def _get_memory() -> Memory:
    global _memory
    if _memory is None:
        _memory = Memory.from_config(CONFIG)
    return _memory


class AddRequest(BaseModel):
    messages: list[dict] | str
    user_id: str | None = None
    agent_id: str | None = None
    app_id: str | None = None
    run_id: str | None = None
    metadata: dict | None = None
    infer: bool = True


class SearchRequest(BaseModel):
    query: str
    user_id: str | None = None
    agent_id: str | None = None
    app_id: str | None = None
    run_id: str | None = None
    limit: int = 5


def _scope_kwargs(req: AddRequest) -> dict:
    # real mem0ai==2.0.11 Memory.add() only accepts user_id/agent_id/run_id --
    # no app_id kwarg (confirmed via inspect.signature against the real lib).
    # app_id is folded into metadata by add_memory() instead, so it's still
    # preserved and filterable (Memory.search() supports arbitrary metadata
    # keys inside the flat `filters` dict, verified against a real pgvector
    # backend).
    return {k: v for k in ("user_id", "agent_id", "run_id") if (v := getattr(req, k))}


def _scope_filter(req: SearchRequest) -> dict | None:
    # Memory.search() requires filters as a flat dict containing at least
    # one of user_id/agent_id/run_id; multiple keys AND together, and extra
    # metadata keys (app_id) ride alongside as plain equality filters --
    # verified for real, not per the Platform API's nested OR/AND scheme.
    scope = {k: v for k in ("user_id", "agent_id", "run_id", "app_id") if (v := getattr(req, k))}
    return scope or None


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/memories")
def add_memory(req: AddRequest) -> dict:
    metadata = dict(req.metadata or {})
    if req.app_id:
        metadata["app_id"] = req.app_id
    result = _get_memory().add(
        req.messages,
        **_scope_kwargs(req),
        metadata=metadata or None,
        infer=req.infer,
    )
    return {"results": result.get("results", result) if isinstance(result, dict) else result}


@app.post("/search")
def search_memories(req: SearchRequest) -> dict:
    result = _get_memory().search(req.query, top_k=req.limit, filters=_scope_filter(req))
    return {"results": result.get("results", result) if isinstance(result, dict) else result}


@app.get("/memories")
def list_memories(
    user_id: str | None = None,
    agent_id: str | None = None,
    run_id: str | None = None,
    app_id: str | None = None,
    limit: int = 50,
) -> dict:
    # mem0ai==2.0.11 Memory.get_all() refuses filters without one of
    # user_id/agent_id/run_id (ValueError, confirmed against the live
    # service) -- but browsing everything is exactly what a management UI
    # needs. get_all() is only that validation + telemetry around
    # _get_all_from_vector_store(), so call the internal directly; pgvector's
    # list() treats an empty filters dict as "no WHERE clause" (verified live).
    scope = {
        k: v
        for k, v in (("user_id", user_id), ("agent_id", agent_id), ("run_id", run_id), ("app_id", app_id))
        if v
    }
    results = _get_memory()._get_all_from_vector_store(scope, limit, False, limit)
    return {"results": results}


@app.delete("/memories/{memory_id}")
def delete_memory(memory_id: str) -> dict:
    _get_memory().delete(memory_id)
    return {"status": "deleted", "id": memory_id}
