from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

SAAS_BASE_URL = "https://api.mem0.ai"
LOCAL_ENDPOINT = "http://127.0.0.1:7000"
PAGE_SIZE = 100
ALL_SCOPE_FILTER = {
    "OR": [
        {"user_id": {"ne": None}},
        {"agent_id": {"ne": None}},
        {"app_id": {"ne": None}},
        {"run_id": {"ne": None}},
    ]
}

Memory = dict[str, object]
Opener = Callable[..., object]


@dataclass(frozen=True)
class MigrationResult:
    fetched: int
    imported: int


def read_api_key(key_file: Path | None = None) -> str:
    if key_file:
        key = key_file.read_text().strip()
    else:
        key = os.environ.get("MEM0_API_KEY", "").strip()
    if not key:
        raise ValueError("MEM0_API_KEY is unset and --key-file was not provided")
    return key


def _json_request(url: str, payload: dict, headers: dict[str, str], opener: Opener) -> object:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with opener(req, timeout=30) as resp:
        return json.loads(resp.read() or b"null")


def _rows(payload: object) -> list[Memory]:
    if isinstance(payload, dict):
        rows = payload.get("results") or payload.get("data") or payload.get("memories") or []
    else:
        rows = payload if isinstance(payload, list) else []
    return [r for r in rows if isinstance(r, dict) and r.get("memory")]


def fetch_saas_memories(
    api_key: str,
    *,
    base_url: str = SAAS_BASE_URL,
    page_size: int = PAGE_SIZE,
    opener: Opener = urllib.request.urlopen,
) -> list[Memory]:
    # Mem0 SaaS's v3 API rejects the `Bearer` scheme (401 token_not_valid);
    # it expects `Token <key>`, matching the official SDK's header.
    headers = {"Authorization": f"Token {api_key}"}
    memories: list[Memory] = []
    page = 1
    while True:
        url = f"{base_url.rstrip('/')}/v3/memories/?page={page}&page_size={page_size}"
        payload = _json_request(url, {"filters": ALL_SCOPE_FILTER}, headers, opener)
        memories.extend(_rows(payload))
        if not (isinstance(payload, dict) and payload.get("next")):
            return memories
        page += 1


def local_payload(memory: Memory) -> dict:
    metadata = dict(memory.get("metadata") or {})
    if memory.get("id"):
        metadata["mem0_saas_id"] = memory["id"]
    payload = {
        "messages": memory["memory"],
        "metadata": metadata,
        "infer": False,
    }
    for key in ("user_id", "agent_id", "app_id", "run_id"):
        if memory.get(key):
            payload[key] = memory[key]
    return payload


def write_local_memory(
    memory: Memory,
    *,
    endpoint: str = LOCAL_ENDPOINT,
    opener: Opener = urllib.request.urlopen,
) -> object:
    return _json_request(f"{endpoint.rstrip('/')}/memories", local_payload(memory), {}, opener)


def migrate_from_saas(
    api_key: str,
    *,
    apply: bool = False,
    fetcher: Callable[..., list[Memory]] = fetch_saas_memories,
    writer: Callable[..., object] = write_local_memory,
) -> MigrationResult:
    memories = fetcher(api_key=api_key)
    if not apply:
        return MigrationResult(fetched=len(memories), imported=0)
    imported = 0
    for memory in memories:
        writer(memory=memory)
        imported += 1
    return MigrationResult(fetched=len(memories), imported=imported)
