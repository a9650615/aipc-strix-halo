"""FastAPI voice/text entrypoint for the agent-orchestrator daemon.

openspec/changes/phase-4-agent tasks 7.1/7.2 — Phase 3 (Pipecat) will POST
here once it exists; this is the reference contract, not that integration.
"""

import uuid

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from aipc_agent.graphs import supervisor

app = FastAPI(title="aipc-agent-orchestrator")
_graph = supervisor()


class ChatRequest(BaseModel):
    text: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    text: str
    task_id: str


@app.get("/healthz")
def healthz() -> dict:
    """Liveness for portal/doctor/voice loop probes (not a model warm check)."""
    return {"status": "ok", "service": "aipc-agent-orchestrator"}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse | JSONResponse:
    task_id = str(uuid.uuid4())
    try:
        result = _graph.invoke({"text": req.text, "session_id": req.session_id or task_id})
    except Exception as exc:
        return JSONResponse(
            status_code=502,
            content={"error": {"code": "upstream_error", "message": str(exc)}},
        )
    return ChatResponse(text=result["text"], task_id=task_id)
