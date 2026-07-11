"""FastAPI voice/text entrypoint for the agent-orchestrator daemon.

Session-aware /chat with end_session, activity listing, and episode log.
"""

from __future__ import annotations

import time
import uuid

from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from aipc_agent.graphs import supervisor
from aipc_agent.stream_chat import iter_chat_sse

app = FastAPI(title="aipc-agent-orchestrator")
_graph = supervisor()


class ChatRequest(BaseModel):
    text: str
    session_id: str | None = None
    source: str | None = None


class ChatResponse(BaseModel):
    text: str
    task_id: str
    end_session: bool = False
    session_id: str = ""
    session_status: str = ""
    spoken_summary: str = ""
    expect_reply: bool = False
    # True when the turn detached to a background job (auto-detach past
    # DETACH_S, or explicit long mode). Always paired with expect_reply=False
    # and end_session=False — the mic frees, no follow-up window.
    background: bool = False


def expect_reply_from_result(result: object) -> bool:
    """True when the graph is asking the user something (clarify_question set).

    Voice clients use this to open a short follow-up listening window instead
    of the default "answered, done" turn (see turn-state-contract).
    """
    if not isinstance(result, dict):
        return False
    return bool(str(result.get("clarify_question") or "").strip())


def background_from_result(result: object) -> bool:
    """True when the turn detached to a background job (graphs._hermes_node's
    auto-detach or explicit long-mode ack). Voice clients free the mic (no
    follow-up) but show a persistent pending pill instead of a "done" card
    until the completion notify replaces it (see turn-state-contract).
    """
    if not isinstance(result, dict):
        return False
    return bool(result.get("background"))


@app.get("/healthz")
def healthz() -> dict:
    from aipc_agent import session_registry
    from aipc_agent.router import ensure_background_refresh, health_snapshot, load_policy

    ensure_background_refresh()
    open_n = len(session_registry.list_sessions(include_done=False, limit=50))
    pol = load_policy()
    return {
        "status": "ok",
        "service": "aipc-agent-orchestrator",
        "stream": True,
        "long_tasks": True,
        "sessions_open": open_n,
        "router": {
            "authoritative": bool(pol.get("authoritative")),
            "paid_enabled": bool(pol.get("paid_enabled")),
            "metered_enabled": bool(pol.get("metered_enabled")),
            "health": health_snapshot(),
        },
    }


@app.get("/router/stats")
def router_stats(limit: int = 200) -> dict:
    """Doctor/portal: redaction-safe route-trace summary (no full user text)."""
    from aipc_agent.router import health_snapshot, summarize_traces

    return {
        "traces": summarize_traces(limit=limit),
        "health": health_snapshot(),
    }


@app.get("/jobs", response_model=None)
def jobs_list(limit: int = 20):
    from aipc_agent import task_jobs

    return {"jobs": task_jobs.job_list(limit=limit)}


@app.get("/jobs/{job_id}", response_model=None)
def jobs_get(job_id: str):
    from aipc_agent import task_jobs

    job = task_jobs.job_get(job_id)
    if not job:
        return JSONResponse(status_code=404, content={"error": "job not found"})
    return job


@app.get("/automation", response_model=None)
def automation_list(include_finished: bool = True):
    from aipc_agent.router import subscription

    return {"automation": subscription.automation_snapshot(include_finished=include_finished)}


@app.post("/automation/{task_id}/cancel", response_model=None)
def automation_cancel(task_id: str):
    from aipc_agent.router import subscription

    result = subscription.cancel(task_id)
    if result.get("type") == "error":
        return JSONResponse(status_code=404, content=result)
    return result


@app.get("/sessions", response_model=None)
def sessions_list(limit: int = 20, include_done: bool = False):
    from aipc_agent import session_registry

    return {
        "sessions": session_registry.list_sessions(
            include_done=include_done, limit=limit
        ),
        "activity": session_registry.activity_snapshot(limit=limit),
    }


@app.get("/sessions/{session_id}", response_model=None)
def sessions_get(session_id: str):
    from aipc_agent import session_registry

    s = session_registry.get(session_id)
    if not s:
        return JSONResponse(status_code=404, content={"error": "session not found"})
    return s


@app.get("/activity", response_model=None)
def activity_list(limit: int = 15):
    from aipc_agent import session_registry

    return {"activity": session_registry.activity_snapshot(limit=limit)}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse | JSONResponse:
    from aipc_agent import episode_log, session_registry

    task_id = str(uuid.uuid4())
    t0 = time.time()
    source = (req.source or "api").strip() or "api"
    sess = session_registry.open_or_resume(
        req.session_id,
        source=source,
        title=(req.text or "")[:40],
    )
    sid = str(sess["id"])
    session_registry.touch(
        sid,
        status="active",
        activity=f"處理：{(req.text or '')[:50]}",
        bump_turn=True,
    )

    try:
        result = _graph.invoke(
            {"text": req.text, "session_id": sid, "source": source}
        )
    except TimeoutError as exc:
        session_registry.touch(sid, status="failed", activity=f"超時：{exc}")
        episode_log.append(
            {
                "task_id": task_id,
                "session_id": sid,
                "user": (req.text or "")[:200],
                "outcome": "timeout",
                "latency_s": time.time() - t0,
            }
        )
        return JSONResponse(
            status_code=504,
            content={
                "error": {
                    "code": "timeout",
                    "message": f"处理超时：{exc}",
                },
                "text": "处理超时了，请简化问题后再试一次。",
                "task_id": task_id,
                "session_id": sid,
                "end_session": False,
            },
        )
    except Exception as exc:
        session_registry.touch(sid, status="failed", activity=f"錯誤：{exc}"[:120])
        episode_log.append(
            {
                "task_id": task_id,
                "session_id": sid,
                "user": (req.text or "")[:200],
                "outcome": "error",
                "error": str(exc)[:200],
                "latency_s": time.time() - t0,
            }
        )
        return JSONResponse(
            status_code=502,
            content={
                "error": {"code": "upstream_error", "message": str(exc)},
                "session_id": sid,
            },
        )

    text = result.get("text") if isinstance(result, dict) else None
    if not text:
        session_registry.touch(sid, activity="空回覆")
        return JSONResponse(
            status_code=502,
            content={
                "error": {"code": "empty_reply", "message": "empty graph reply"},
                "text": "没有生成回复，请再说一次。",
                "task_id": task_id,
                "session_id": sid,
            },
        )

    end_session = bool(result.get("end_session")) if isinstance(result, dict) else False
    # Detect waiting_user from clarify-style replies is hard; status from graph if present
    st = "done" if end_session else "active"
    if isinstance(result, dict) and result.get("session_status") in (
        "active",
        "working",
        "waiting_user",
        "done",
        "failed",
    ):
        st = str(result["session_status"])

    if end_session:
        session_registry.complete(sid, reason="end_session")
        st = "done"
    else:
        from aipc_agent import task_jobs

        cur = session_registry.get(sid) or {}
        jid = cur.get("job_id")
        job_running = False
        if jid:
            job = task_jobs.job_get(str(jid))
            job_running = bool(job and job.get("status") == "running")
        if job_running:
            st = "working"
            session_registry.touch(
                sid,
                status="working",
                activity=cur.get("last_activity") or "任務執行中…",
            )
        else:
            # clarify-style: short question often waiting for slot fill
            reply_s = str(text)
            if any(
                k in reply_s
                for k in ("要查哪", "哪支股票", "请说", "請說", "还是没听清", "還是沒聽清")
            ):
                st = "waiting_user"
            else:
                st = "active"
            session_registry.touch(
                sid,
                status=st,
                activity=reply_s[:80],
                clear_job=True,
            )

    trail = ""
    if isinstance(result, dict):
        trail = str(result.get("learn_trail") or result.get("trail") or "")[:2000]
    episode_log.append(
        {
            "task_id": task_id,
            "session_id": sid,
            "user": (req.text or "")[:200],
            "reply": str(text)[:300],
            "end_session": end_session,
            "outcome": "ok",
            "latency_s": round(time.time() - t0, 3),
            "target": (result.get("target") if isinstance(result, dict) else None),
            "learn_trail": trail or None,
        }
    )

    spoken = ""
    if isinstance(result, dict):
        spoken = str(result.get("spoken_summary") or "").strip()
    if not spoken and text:
        try:
            from aipc_agent.router.spoken import spoken_summary

            spoken = spoken_summary(str(text))
        except Exception:
            spoken = ""

    return ChatResponse(
        text=str(text),
        task_id=task_id,
        end_session=end_session,
        session_id=sid,
        session_status=st,
        spoken_summary=spoken,
        expect_reply=expect_reply_from_result(result),
        background=background_from_result(result),
    )


@app.post("/chat/stream")
def chat_stream(req: ChatRequest) -> StreamingResponse:
    """SSE token stream for voice turns (see aipc_agent.stream_chat)."""
    from aipc_agent import session_registry

    sess = session_registry.open_or_resume(req.session_id, source=req.source or "stream")
    sid = str(sess["id"])

    def _gen():
        yield from iter_chat_sse(req.text, sid)

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
