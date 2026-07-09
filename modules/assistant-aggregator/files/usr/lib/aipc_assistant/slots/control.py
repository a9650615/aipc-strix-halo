from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from aipc_assistant.paths import controller_path
from aipc_assistant.slots import keywords as keywords_slot
from aipc_assistant.types import ALLOWED_ACTIONS, Action

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore


def _load_controller_cfg(path: Path | None = None) -> dict[str, Any]:
    # Merge runtime.yaml control defaults (NPU-first) under controller.yaml
    base: dict[str, Any] = {
        "enabled": True,
        "model": "resident-small",
        "litellm_base": "http://127.0.0.1:4000/v1",
        "prompt_style": "json_content",
        "timeout_s": 8,
        "confidence_min": 0.55,
    }
    try:
        from aipc_assistant.paths import etc_dir

        rt_path = etc_dir() / "runtime.yaml"
        if rt_path.is_file() and yaml is not None:
            rt = yaml.safe_load(rt_path.read_text(encoding="utf-8")) or {}
            ctrl = (rt.get("control") or {}) if isinstance(rt, dict) else {}
            if isinstance(ctrl, dict):
                base.update({k: v for k, v in ctrl.items() if v is not None})
    except Exception:
        pass
    p = path or controller_path()
    if p.is_file() and yaml is not None:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if isinstance(data, dict):
            base.update(data)
    # Force allow-list: never accidentally point control at cloud/large models
    allow = base.get("allow_models") or ["resident-small"]
    if isinstance(allow, list) and base.get("model") not in allow:
        base["model"] = "resident-small"
    return base


def _model_decide(text: str, cfg: dict[str, Any]) -> list[Action]:
    if not cfg.get("enabled"):
        return []
    model = str(cfg.get("model") or "resident-small")
    base = str(cfg.get("litellm_base") or "http://127.0.0.1:4000/v1").rstrip("/")
    timeout = float(cfg.get("timeout_s") or 8)
    conf_min = float(cfg.get("confidence_min") or 0.55)
    allowed = ", ".join(sorted(ALLOWED_ACTIONS))
    system = (
        "You are the aipc assistant control plane. "
        f"Reply with ONE JSON object only: "
        f'{{"action":"<one of: {allowed}>","confidence":0.0,"reason":"short"}}. '
        "No markdown. Prefer action none unless the user clearly wants "
        "end session, local mode, online mode, or stop voice."
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ],
        "temperature": 0,
        "max_tokens": 128,
    }
    try:
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
            content = "".join(
                b.get("text", "") if isinstance(b, dict) else str(b) for b in content
            )
        content = str(content).strip()
        if content.startswith("```"):
            content = content.strip("`")
            if content.startswith("json"):
                content = content[4:].strip()
        obj = json.loads(content)
        action = str(obj.get("action") or "none")
        conf = float(obj.get("confidence") or 0)
        if action not in ALLOWED_ACTIONS or conf < conf_min:
            return []
        if action == "none":
            return []
        return [
            Action(
                name=action,
                source="controller",
                confidence=conf,
                args={"reason": str(obj.get("reason") or "")},
            )
        ]
    except (
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
        OSError,
    ):
        return []


def decide(text: str, role: str = "user") -> list[Action]:
    # Explicit lifecycle keywords always win (close window / mode switch).
    kw = keywords_slot.match_actions(text, role=role)
    strong = [a for a in kw if a.name in ("session_close", "mode_local", "mode_online")]
    if strong:
        return strong
    cfg = _load_controller_cfg()
    actions = _model_decide(text, cfg)
    if actions:
        return actions
    return kw
