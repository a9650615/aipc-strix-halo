from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


def _load_server_module(monkeypatch):
    fastapi = types.SimpleNamespace(FastAPI=lambda **kwargs: _FakeApp())
    mem0 = types.SimpleNamespace(Memory=types.SimpleNamespace(from_config=lambda config: None))
    pydantic = types.SimpleNamespace(BaseModel=_BaseModel)
    monkeypatch.setitem(sys.modules, "fastapi", fastapi)
    monkeypatch.setitem(sys.modules, "mem0", mem0)
    monkeypatch.setitem(sys.modules, "pydantic", pydantic)

    p = Path(__file__).resolve().parents[2] / "modules/memory-mem0/files/usr/lib/aipc-mem0/aipc_mem0/server.py"
    spec = importlib.util.spec_from_file_location("aipc_mem0_server_for_test", p)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class _FakeApp:
    def get(self, path):
        return lambda fn: fn

    def post(self, path):
        return lambda fn: fn

    def delete(self, path):
        return lambda fn: fn


class _BaseModel:
    def __init__(self, **kwargs):
        for name, default in getattr(self, "__class__", type(self)).__dict__.items():
            if name.startswith("_") or callable(default):
                continue
            setattr(self, name, kwargs.pop(name, default))
        for name, value in kwargs.items():
            setattr(self, name, value)


class _FakeMemory:
    def __init__(self) -> None:
        self.calls = []

    def add(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return {"results": [{"memory": messages}]}


def test_add_memory_passes_only_real_entity_kwargs_and_folds_app_id_into_metadata(monkeypatch):
    # real mem0ai==2.0.11 Memory.add() only accepts user_id/agent_id/run_id --
    # no app_id kwarg (confirmed via inspect.signature against the real lib).
    server = _load_server_module(monkeypatch)
    fake = _FakeMemory()
    monkeypatch.setattr(server, "_get_memory", lambda: fake)

    req = server.AddRequest(
        messages="remember this",
        user_id="u",
        agent_id="a",
        app_id="app",
        run_id="r",
        metadata={"source": "saas"},
        infer=False,
    )

    server.add_memory(req)

    assert fake.calls == [
        (
            "remember this",
            {
                "user_id": "u",
                "agent_id": "a",
                "run_id": "r",
                "metadata": {"source": "saas", "app_id": "app"},
                "infer": False,
            },
        )
    ]


def test_add_memory_without_app_id_leaves_metadata_untouched(monkeypatch):
    server = _load_server_module(monkeypatch)
    fake = _FakeMemory()
    monkeypatch.setattr(server, "_get_memory", lambda: fake)

    req = server.AddRequest(messages="remember this", user_id="u", metadata={"source": "saas"})

    server.add_memory(req)

    assert fake.calls[0][1]["metadata"] == {"source": "saas"}


def test_search_uses_flat_and_filter_for_all_scopes(monkeypatch):
    # real mem0ai Memory.search() requires filters as a flat dict (at least
    # one of user_id/agent_id/run_id at top level); multiple keys AND
    # together, and arbitrary metadata keys (like app_id, once folded into
    # metadata by add_memory) can ride alongside as extra flat filter keys --
    # verified against the real library + real pgvector backend.
    server = _load_server_module(monkeypatch)
    seen = {}

    class FakeMemory:
        def search(self, query, **kwargs):
            seen.update(kwargs)
            return {"results": []}

    monkeypatch.setattr(server, "_get_memory", lambda: FakeMemory())
    req = server.SearchRequest(query="q", user_id="u", agent_id="a", app_id="app", run_id="r", limit=3)

    server.search_memories(req)

    assert seen["top_k"] == 3
    assert seen["filters"] == {"user_id": "u", "agent_id": "a", "run_id": "r", "app_id": "app"}


def test_list_memories_bypasses_get_all_entity_validation(monkeypatch):
    # real mem0ai==2.0.11 Memory.get_all() raises ValueError unless filters
    # contains user_id/agent_id/run_id (confirmed live) -- the management UI
    # must be able to browse everything, so the endpoint calls
    # _get_all_from_vector_store() (the internal get_all() wraps) directly.
    server = _load_server_module(monkeypatch)
    calls = []

    class FakeMemory:
        def _get_all_from_vector_store(self, filters, limit, show_expired=False, output_limit=None):
            calls.append((filters, limit, show_expired, output_limit))
            return [{"id": "m1"}]

    monkeypatch.setattr(server, "_get_memory", lambda: FakeMemory())

    result = server.list_memories(user_id="u", app_id="app", limit=7)
    assert calls == [({"user_id": "u", "app_id": "app"}, 7, False, 7)]
    assert result == {"results": [{"id": "m1"}]}

    server.list_memories()
    assert calls[-1] == ({}, 50, False, 50)


def test_delete_memory_forwards_id(monkeypatch):
    server = _load_server_module(monkeypatch)
    deleted = []

    class FakeMemory:
        def delete(self, memory_id):
            deleted.append(memory_id)

    monkeypatch.setattr(server, "_get_memory", lambda: FakeMemory())

    result = server.delete_memory("abc-123")

    assert deleted == ["abc-123"]
    assert result == {"status": "deleted", "id": "abc-123"}
