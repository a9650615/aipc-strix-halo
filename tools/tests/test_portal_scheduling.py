from __future__ import annotations

import json
import sys
import threading
import urllib.request
from pathlib import Path

PORTAL_LIB = Path(__file__).parents[2] / "modules/system-aipc-portal/files/usr/lib/aipc-portal"
sys.path.insert(0, str(PORTAL_LIB))

from aipc_portal import scheduling, server  # noqa: E402


def test_evaluate_loaded_keep_warm_blocks_unload() -> None:
    policy = {**scheduling.DEFAULT_POLICY, "keep_warm_mem_floor_gb": 25.0, "max_gpu_loaded": 2}
    capacity = {"mem_available_gb": 40.0}
    live = {
        "models": [
            {
                "model_name": "Ornith-1.0-35B",
                "loaded": True,
                "pinned": False,
                "status": "ready",
                "device": "gpu",
                "last_use": 0,  # very old in mono-ms terms if now is large
            }
        ]
    }
    manifest = [
        {
            "alias": "ornith-35b",
            "model_id": "Ornith-1.0-35B",
            "idle_unload_after_s": 60,
            "tier": "floating",
            "size_gb": 22,
            "backend": "lemonade",
        }
    ]
    rows = scheduling.evaluate_loaded(live, manifest, policy, capacity)
    assert rows[0]["decision"] == "keep_warm"
    assert rows[0]["unload_candidate"] is False


def test_evaluate_loaded_marks_unload_when_ram_tight(monkeypatch) -> None:
    policy = {**scheduling.DEFAULT_POLICY, "keep_warm_mem_floor_gb": 25.0}
    capacity = {"mem_available_gb": 10.0}
    # Force mono clock so age >> threshold
    monkeypatch.setattr(scheduling.time, "monotonic", lambda: 10_000.0)
    live = {
        "models": [
            {
                "model_name": "Ornith-1.0-35B",
                "loaded": True,
                "pinned": False,
                "status": "ready",
                "device": "gpu",
                "last_use": 1_000.0,  # age = 10000 - 1 = 9999s
            }
        ]
    }
    manifest = [
        {
            "alias": "ornith-35b",
            "model_id": "Ornith-1.0-35B",
            "idle_unload_after_s": 300,
            "tier": "floating",
            "backend": "lemonade",
        }
    ]
    rows = scheduling.evaluate_loaded(live, manifest, policy, capacity)
    assert rows[0]["decision"] == "unload_candidate"
    assert rows[0]["unload_candidate"] is True


def test_in_use_never_unload_candidate(monkeypatch) -> None:
    policy = {**scheduling.DEFAULT_POLICY, "keep_warm_mem_floor_gb": 25.0}
    capacity = {"mem_available_gb": 5.0}
    monkeypatch.setattr(scheduling.time, "monotonic", lambda: 10_000.0)
    live = {
        "models": [
            {
                "model_name": "Ornith-1.0-35B",
                "loaded": True,
                "pinned": False,
                "status": "in_use",
                "device": "gpu",
                "last_use": 1_000.0,
            }
        ]
    }
    manifest = [
        {"alias": "ornith-35b", "model_id": "Ornith-1.0-35B", "idle_unload_after_s": 10, "backend": "lemonade"}
    ]
    rows = scheduling.evaluate_loaded(live, manifest, policy, capacity)
    assert rows[0]["decision"] == "in_use"
    assert rows[0]["unload_candidate"] is False


def test_lemonade_live_keeps_last_good_on_probe_miss(monkeypatch) -> None:
    import aipc_portal.scheduling as sched

    sched._lemonade_last_good = {
        "availability": "available",
        "models": [{"model_name": "kept", "loaded": True}],
        "max_models": {"llm": 2},
        "pinned_models": {},
        "stale": False,
    }
    sched._lemonade_last_good_at = __import__("time").monotonic()
    monkeypatch.setattr(sched, "_http_json", lambda *a, **k: {})
    live = sched.lemonade_live()
    assert live["availability"] == "stale"
    assert live["models"][0]["model_name"] == "kept"


def test_models_api_route(monkeypatch, tmp_path: Path) -> None:
    static = tmp_path / "static"
    (static / "models").mkdir(parents=True)
    (static / "models" / "index.html").write_text("<h1>Models</h1>", encoding="utf-8")
    monkeypatch.setattr(server, "STATIC_ROOT", static)

    payload = {"summary": "ok", "loaded": [], "policy": {}, "capacity": {}}
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    tag = '"' + __import__("hashlib").sha256(body).hexdigest()[:16] + '"'
    monkeypatch.setattr(
        server,
        "scheduling_snapshot_cached",
        lambda: (payload, body, tag),
    )
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_port}"
    try:
        assert urllib.request.urlopen(f"{base}/models").read() == b"<h1>Models</h1>"
        req = urllib.request.Request(f"{base}/api/v1/models")
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            assert resp.headers.get("ETag") == tag
            data = json.load(resp)
        assert data["summary"] == "ok"
        # 304 on matching ETag
        req2 = urllib.request.Request(
            f"{base}/api/v1/models",
            headers={"If-None-Match": tag},
        )
        try:
            urllib.request.urlopen(req2)
            raised = False
        except urllib.error.HTTPError as err:
            raised = err.code == 304
        assert raised
    finally:
        httpd.shutdown()
        thread.join()
