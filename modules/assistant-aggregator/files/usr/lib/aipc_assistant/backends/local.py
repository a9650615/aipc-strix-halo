"""Local fulfillment — default NPU via LiteLLM (resident-small)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore

from aipc_assistant.paths import etc_dir


def _load_runtime() -> dict[str, Any]:
    p = etc_dir() / "runtime.yaml"
    if p.is_file() and yaml is not None:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if isinstance(data, dict):
            return data
    return {
        "npu_first": True,
        "local_backend": {
            "mode": "npu",
            "model": "resident-small",
            "litellm_base": "http://127.0.0.1:4000/v1",
            "timeout_s": 60,
            "agent_url": "http://127.0.0.1:4100/chat",
        },
    }


def _npu_chat(text: str, cfg: dict[str, Any], session_id: str | None) -> str:
    base = str(
        os.environ.get("AIPC_LITELLM_BASE")
        or cfg.get("litellm_base")
        or "http://127.0.0.1:4000/v1"
    ).rstrip("/")
    model = str(
        os.environ.get("AIPC_ASSISTANT_NPU_MODEL")
        or cfg.get("model")
        or "resident-small"
    )
    timeout = float(cfg.get("timeout_s") or 60)
    system = str(
        cfg.get("system_prompt")
        or "You are the aipc on-device assistant. Be concise. Reply in the user's language."
    ).strip()
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ],
        "temperature": 0.4,
        "max_tokens": 1024,
        # help some gateways attribute sessions
        "user": session_id or "aipc-assistant-npu",
    }
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode())
    content = data["choices"][0]["message"]["content"]
    if isinstance(content, list):
        # reasoning models may return block lists
        parts = []
        for b in content:
            if isinstance(b, dict):
                if b.get("type") in (None, "text") and b.get("text"):
                    parts.append(str(b["text"]))
                elif b.get("type") == "thinking":
                    continue
            else:
                parts.append(str(b))
        content = "".join(parts) if parts else str(content)
    return str(content).strip()


def _agent_chat(text: str, session_id: str | None, cfg: dict[str, Any]) -> str:
    url = os.environ.get("AIPC_VOICE_CHAT_URL") or cfg.get("agent_url") or "http://127.0.0.1:4100/chat"
    sid = session_id or str(uuid.uuid4())
    body = json.dumps({"text": text, "session_id": sid}).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode())
    if isinstance(data, dict):
        if "text" in data:
            return str(data["text"])
        if "error" in data:
            err = data["error"]
            if isinstance(err, dict):
                return f"error: {err.get('message') or err}"
            return f"error: {err}"
    return str(data)


def chat(text: str, session_id: str | None = None) -> str:
    """Fulfill local turn. Default: NPU resident-small via LiteLLM."""
    rt = _load_runtime()
    lb = rt.get("local_backend") or {}
    if not isinstance(lb, dict):
        lb = {}
    mode = str(os.environ.get("AIPC_ASSISTANT_LOCAL_BACKEND") or lb.get("mode") or "npu").lower()

    def _npu_or_raise() -> str:
        try:
            out = _npu_chat(text, lb, session_id)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            raise RuntimeError(
                f"NPU chat via LiteLLM HTTP {e.code}: {detail} "
                f"(model={lb.get('model', 'resident-small')})"
            ) from e
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"LiteLLM unreachable for NPU model: {e}. "
                "Start litellm + lemonade (resident-small on NPU)."
            ) from e
        except (KeyError, IndexError, json.JSONDecodeError, TypeError) as e:
            raise RuntimeError(f"bad NPU chat response: {e}") from e
        if not out:
            raise RuntimeError("NPU chat returned empty text")
        return out

    def _agent_or_raise() -> str:
        try:
            out = _agent_chat(text, session_id, lb)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            raise RuntimeError(f"local agent HTTP {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"local agent unreachable: {e}") from e
        if not out or out.startswith("error:"):
            raise RuntimeError(f"local agent bad reply: {out!r}")
        return out

    if mode == "agent":
        return _agent_or_raise()

    if mode == "auto":
        npu_err: Exception | None = None
        try:
            return _npu_or_raise()
        except Exception as exc:  # noqa: BLE001 — fall through to agent
            npu_err = exc
        try:
            return _agent_or_raise()
        except Exception as agent_exc:
            raise RuntimeError(
                f"npu and agent local backends failed: npu={npu_err}; agent={agent_exc}"
            ) from agent_exc

    # default npu
    return _npu_or_raise()


def npu_reachable() -> tuple[bool, str]:
    """Cheap probe for onboarding (models list or tiny completion)."""
    rt = _load_runtime()
    lb = rt.get("local_backend") or {}
    base = str(lb.get("litellm_base") or "http://127.0.0.1:4000/v1").rstrip("/")
    model = str(lb.get("model") or "resident-small")
    try:
        req = urllib.request.Request(f"{base}/models", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read().decode())
        ids = [m.get("id") for m in data.get("data") or [] if isinstance(m, dict)]
        if model in ids or any(model in str(i) for i in ids):
            return True, f"LiteLLM has {model}"
        if ids:
            return True, f"LiteLLM up (models={len(ids)}; want {model})"
        return True, "LiteLLM up"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
