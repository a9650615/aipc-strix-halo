from collections.abc import Callable
from typing import Any

from aipc_agent.glm_tool import consult_glm


def consult_models(
    question: str,
    advisors: list[str] | None = None,
    *,
    run_glm: Callable[[str], dict[str, Any]] = consult_glm,
) -> dict[str, Any]:
    selected = list(dict.fromkeys(advisors or ["glm"]))
    unknown = [name for name in selected if name != "glm"]
    if unknown:
        return {
            "status": "error",
            "detail": f"unknown advisors: {', '.join(unknown)}",
            "available_advisors": ["glm"],
        }
    results = [run_glm(question) for _ in selected]
    return {
        "status": "ok"
        if all(result.get("status") == "ok" for result in results)
        else "partial",
        "advisors": results,
    }
