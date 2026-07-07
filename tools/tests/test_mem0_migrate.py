from __future__ import annotations

import json
from pathlib import Path

import pytest

from aipc_lib import mem0_migrate


class _FakeResponse:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()


def test_fetch_saas_memories_uses_v3_pagination_and_scope_wildcard() -> None:
    calls = []

    def opener(req, timeout: float = 30):
        calls.append(req)
        if "page=1" in req.full_url:
            return _FakeResponse(
                {
                    "results": [
                        {
                            "id": "m1",
                            "memory": "likes local-first tools",
                            "user_id": "birdyo",
                            "agent_id": "agent",
                            "app_id": "aipc",
                            "run_id": "run-1",
                        }
                    ],
                    "next": "yes",
                }
            )
        return _FakeResponse({"results": [], "next": None})

    rows = mem0_migrate.fetch_saas_memories("m0-secret", opener=opener)

    assert rows[0]["user_id"] == "birdyo"
    assert rows[0]["agent_id"] == "agent"
    assert rows[0]["app_id"] == "aipc"
    assert rows[0]["run_id"] == "run-1"
    assert len(calls) == 2
    body = json.loads(calls[0].data.decode())
    assert body["filters"] == mem0_migrate.ALL_SCOPE_FILTER
    assert calls[0].headers["Authorization"] == "Token m0-secret"


def test_migrate_dry_run_does_not_write_local() -> None:
    def fetcher(**kwargs):
        return [{"memory": "one", "user_id": "u"}]

    def writer(**kwargs):  # pragma: no cover - should not run
        raise AssertionError("dry-run wrote local memory")

    result = mem0_migrate.migrate_from_saas("m0-secret", apply=False, fetcher=fetcher, writer=writer)

    assert result.fetched == 1
    assert result.imported == 0


def test_migrate_apply_preserves_all_scopes_in_local_payload() -> None:
    written = []

    def fetcher(**kwargs):
        return [
            {
                "id": "m1",
                "memory": "remember this",
                "user_id": "u",
                "agent_id": "a",
                "app_id": "app",
                "run_id": "r",
                "metadata": {"kind": "pref"},
            }
        ]

    def writer(memory, **kwargs):
        written.append(mem0_migrate.local_payload(memory))

    result = mem0_migrate.migrate_from_saas("m0-secret", apply=True, fetcher=fetcher, writer=writer)

    assert result.imported == 1
    assert written == [
        {
            "messages": "remember this",
            "user_id": "u",
            "agent_id": "a",
            "app_id": "app",
            "run_id": "r",
            "metadata": {"kind": "pref", "mem0_saas_id": "m1"},
            "infer": False,
        }
    ]


def test_read_api_key_prefers_file_without_leaking_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    key_file = tmp_path / "key.txt"
    key_file.write_text("m0-file-secret\n")
    monkeypatch.setenv("MEM0_API_KEY", "m0-env-secret")

    assert mem0_migrate.read_api_key(key_file) == "m0-file-secret"
