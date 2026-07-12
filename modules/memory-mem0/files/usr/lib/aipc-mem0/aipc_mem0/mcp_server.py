"""Local stdio MCP server wrapping the local mem0 (memory-mem0, Phase 2).

The official mem0 Claude plugin ships ONLY a remote HTTP MCP pointed at the
Mem0 SaaS (https://mcp.mem0.ai/mcp/), authenticated with MEM0_API_KEY -- it has
no local/self-hosted mode, and mem0ai==2.0.11 ships no MCP entrypoint at all
(no `mcp` dep installed, no `mem0 mcp` CLI). This module is the local
equivalent: a stdio MCP server wrapping the real `mem0.Memory` configured
against the LOCAL stack (pgvector via db-postgres + LiteLLM gateway on :4000
for the resident-small (NPU) LLM and embed-bge embedder), so agents store and search
memories LOCALLY instead of hitting the SaaS quota.

Same tool surface as the platform MCP (add_memory, search_memories, get_memories,
get_memory, delete_memory, delete_all_memories), so an agent's memory skills/hooks
keep working unchanged when this server is wired in via its MCP config:

  Claude (plugin .mcp.json) / opencode (config.json `mcp`) / hermes (config.yaml
  `mcp_servers`) all point a `mem0` server at:
    command: <venv>/bin/python  args: ["-m","aipc_mem0.mcp_server"]
    env:     {"PYTHONPATH": "<aipc_mem0 dir>", "MEM0_TELEMETRY": "False"}

MEM0_TELEMETRY is set before importing mem0: the SDK phones home to PostHog
(us.i.posthog.com) on every call otherwise, violating the offline requirement
(CLAUDE.md §6). The systemd unit sets it too, but this server is launched by
agents (not systemd), so it must self-set.
"""
from __future__ import annotations

import os

os.environ.setdefault("MEM0_TELEMETRY", "False")

from mcp.server.fastmcp import FastMCP  # noqa: E402

from aipc_mem0.server import CONFIG  # noqa: E402  -- reuse the exact local config
from mem0 import Memory  # noqa: E402

_memory: Memory | None = None


def _get_memory() -> Memory:
    global _memory
    if _memory is None:
        _memory = Memory.from_config(CONFIG)
    return _memory


def _filter(user_id, agent_id, run_id, app_id) -> dict | None:
    # mem0 Memory.search()/get_all() take a FLAT `filters` dict (not the nested
    # OR/AND scheme the Platform API docs describe) -- verified against a real
    # pgvector backend. app_id is not a first-class field in mem0ai==2.0.11
    # (add() has no app_id kwarg), so it rides as a plain equality filter here,
    # matching aipc_mem0/server.py's _scope_filter.
    f = {
        k: v
        for k, v in (
            ("user_id", user_id),
            ("agent_id", agent_id),
            ("run_id", run_id),
            ("app_id", app_id),
        )
        if v
    }
    return f or None


mcp = FastMCP("mem0")


@mcp.tool()
def add_memory(
    text: str,
    user_id: str | None = None,
    agent_id: str | None = None,
    app_id: str | None = None,
    run_id: str | None = None,
    metadata: dict | None = None,
    infer: bool = True,
) -> dict:
    """Store a memory (a fact or piece of text). With infer=True (default) the
    local LLM extracts structured facts; infer=False stores the text verbatim."""
    md = dict(metadata or {})
    if app_id:
        md["app_id"] = app_id
    kwargs = {
        k: v for k, v in (("user_id", user_id), ("agent_id", agent_id), ("run_id", run_id)) if v
    }
    return _get_memory().add(text, metadata=md or None, infer=infer, **kwargs)


@mcp.tool()
def search_memories(
    query: str,
    user_id: str | None = None,
    agent_id: str | None = None,
    app_id: str | None = None,
    run_id: str | None = None,
    limit: int = 5,
) -> dict:
    """Semantic search over LOCAL memories (bge-m3 embeddings + pgvector)."""
    # Same bypass as aipc_mem0/server.py's search_memories: Memory.search()
    # refuses filters without one of user_id/agent_id/run_id, but an unscoped
    # search is a normal call shape here. _search_vector_store has no such
    # restriction and PGVector tolerates empty filters (no WHERE clause).
    filters = _filter(user_id, agent_id, run_id, app_id)
    return {"results": _get_memory()._search_vector_store(query, filters or {}, limit)}


@mcp.tool()
def get_memories(
    user_id: str | None = None,
    agent_id: str | None = None,
    app_id: str | None = None,
    run_id: str | None = None,
    limit: int = 20,
) -> dict:
    """List memories for a given scope (user/agent/app/run)."""
    # Same fix as aipc_mem0/server.py's list_memories: PGVector.list() has no
    # ORDER BY, so a bare top_k=limit silently drops the newest rows once the
    # scope grows past `limit`. Over-fetch and sort by created_at ourselves.
    filters = _filter(user_id, agent_id, run_id, app_id)
    results = _get_memory()._get_all_from_vector_store(filters or {}, 10000, False, 10000)
    results.sort(key=lambda m: m.get("created_at") or "", reverse=True)
    return {"results": results[:limit]}


@mcp.tool()
def get_memory(memory_id: str) -> dict:
    """Fetch a single memory by id."""
    return _get_memory().get(memory_id)


@mcp.tool()
def delete_memory(memory_id: str) -> dict:
    """Delete a single memory by id."""
    return _get_memory().delete(memory_id)


@mcp.tool()
def delete_all_memories(
    user_id: str | None = None,
    agent_id: str | None = None,
    run_id: str | None = None,
) -> dict:
    """Delete all memories for a given scope."""
    return _get_memory().delete_all(user_id=user_id, agent_id=agent_id, run_id=run_id)


if __name__ == "__main__":
    mcp.run()
