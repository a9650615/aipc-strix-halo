from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "files/usr/lib/aipc-agent"
sys.path.insert(0, str(ROOT))

consult_models = import_module("aipc_agent.dynamic_moa").consult_models


def test_default_advisor_is_glm() -> None:
    calls: list[str] = []
    result = consult_models(
        "review this",
        run_glm=lambda question: (
            calls.append(question)
            or {
                "status": "ok",
                "advisor": "glm",
                "content": "answer",
            }
        ),
    )
    assert calls == ["review this"]
    assert result == {
        "status": "ok",
        "advisors": [{"status": "ok", "advisor": "glm", "content": "answer"}],
    }


def test_unknown_advisor_fails_without_calling_glm() -> None:
    result = consult_models("review this", ["unknown"], run_glm=lambda _: None)
    assert result == {
        "status": "error",
        "detail": "unknown advisors: unknown",
        "available_advisors": ["glm"],
    }
