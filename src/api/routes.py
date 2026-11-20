"""FastAPI HTTP endpoints for multi-agent chat, health probes, metrics, traces, alerts, and dashboard."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from src.api.auth import (
    AUTH_COOKIE_NAME,
    Principal,
    RoleType,
    TokenIssueRequest,
    TokenIssueResponse,
    assert_user_access,
    create_access_token,
    decode_access_token,
    get_current_principal,
    require_roles,
    verify_bootstrap_issuance,
)
from src.api.dashboard import DASHBOARD_HTML, DASHBOARD_LOGIN_HTML
from src.api.rate_limit import rate_limiter, token_budget_tracker
from src.api.schemas import (
    ChatRequest,
    ChatResponse,
    EvalRunRequest,
    HandoffResumeRequest,
    HandoffSummary,
    HealthResponse,
)
from src.config.settings import settings
from src.observability.tracer import trace_recorder
from src.orchestration.graph import (
    execute_orchestration,
    execute_orchestration_stream,
    resume_orchestration,
)
from src.orchestration.persistence import handoff_store
from src.orchestration.session_store import session_store
from src.rag.vector_store import get_vector_store

router = APIRouter()
_optional_bearer = HTTPBearer(auto_error=False)


class SessionLoginRequest(BaseModel):
    """Browser login payload for establishing an HttpOnly operator/merchant cookie session."""

    user_id: str = Field(default="operator_1", min_length=1, max_length=128)
    role: RoleType = Field(default="operator")
    bootstrap_key: str | None = Field(default=None)
    access_token: str | None = Field(default=None)


@router.post("/auth/token", response_model=TokenIssueResponse, tags=["Security & Auth"])
async def issue_token_endpoint(
    payload: TokenIssueRequest,
    x_bootstrap_key: str | None = Header(default=None, alias="X-Bootstrap-Key"),
) -> TokenIssueResponse:
    """Issue a signed Bearer JWT for merchant or operator/admin access."""
    verify_bootstrap_issuance(payload.role, bootstrap_key=x_bootstrap_key)
    ttl = int(payload.expires_in_seconds or settings.auth_token_ttl_seconds)
    token = create_access_token(
        user_id=payload.user_id,
        role=payload.role,
        expires_in_seconds=ttl,
    )
    return TokenIssueResponse(
        access_token=token,
        expires_in=ttl,
        user_id=payload.user_id.strip(),
        role=payload.role,
    )


@router.post("/auth/session", response_model=TokenIssueResponse, tags=["Security & Auth"])
async def create_browser_session_endpoint(
    payload: SessionLoginRequest,
    response: Response,
) -> TokenIssueResponse:
    """Authenticate a browser session via existing operator JWT or bootstrap key and set an HttpOnly cookie."""
    ttl = int(settings.auth_token_ttl_seconds)
    if payload.access_token:
        raw_tok = payload.access_token.strip()
        if raw_tok.lower().startswith("bearer "):
            raw_tok = raw_tok[7:].strip()
        principal = decode_access_token(raw_tok)
        if principal.role not in ("operator", "admin"):
            raise HTTPException(
                status_code=403,
                detail="Only operator or admin tokens may open an ops dashboard session.",
            )
        token = raw_tok
        uid = principal.user_id
        role = principal.role
    else:
        verify_bootstrap_issuance(payload.role, bootstrap_key=payload.bootstrap_key)
        uid = payload.user_id.strip()
        role = payload.role
        token = create_access_token(user_id=uid, role=role, expires_in_seconds=ttl)

    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=token,
        max_age=ttl,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return TokenIssueResponse(
        access_token=token,
        expires_in=ttl,
        user_id=uid,
        role=role,
    )


@router.post("/auth/logout", tags=["Security & Auth"])
async def logout_browser_session_endpoint(response: Response) -> dict[str, str]:
    """Clear the HttpOnly authentication session cookie."""
    response.delete_cookie(key=AUTH_COOKIE_NAME, path="/")
    return {"status": "logged_out"}


@router.post("/chat", response_model=ChatResponse, tags=["Multi-Agent Orchestration"])
@router.post("/", response_model=ChatResponse, tags=["Multi-Agent Orchestration"])
@router.post("/api/v1/message", response_model=ChatResponse, tags=["Multi-Agent Orchestration"])
async def chat_endpoint(
    payload: ChatRequest,
    principal: Principal = Depends(get_current_principal),
) -> ChatResponse:
    """Process an incoming user message through the 5-agent LangGraph orchestration."""
    assert_user_access(principal, payload.user_id)
    rate_limiter.check_and_consume(f"{principal.role}:{principal.user_id}")
    token_budget_tracker.check_budget(payload.user_id)

    result = execute_orchestration(
        message=payload.message,
        user_id=payload.user_id,
    )
    token_budget_tracker.record_usage(
        payload.user_id,
        int(result.get("total_tokens") or 0),
    )
    return ChatResponse(**result)


@router.post("/chat/stream", tags=["Multi-Agent Orchestration"])
async def chat_stream_endpoint(
    payload: ChatRequest,
    principal: Principal = Depends(get_current_principal),
) -> StreamingResponse:
    """Stream multi-agent orchestration events and real-time LLM token generation via Server-Sent Events (SSE)."""
    assert_user_access(principal, payload.user_id)
    rate_limiter.check_and_consume(f"{principal.role}:{principal.user_id}")
    token_budget_tracker.check_budget(payload.user_id)

    async def event_generator():
        async for event in execute_orchestration_stream(
            message=payload.message,
            user_id=payload.user_id,
        ):
            if event.get("event") == "final_result":
                data = event.get("data") or {}
                token_budget_tracker.record_usage(
                    payload.user_id,
                    int(data.get("total_tokens") or 0),
                )
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/chat/history/{user_id}", tags=["Multi-Agent Orchestration"])
async def get_chat_history_endpoint(
    user_id: str,
    principal: Principal = Depends(get_current_principal),
) -> dict[str, Any]:
    """Retrieve conversational history for the given user_id (tenant-isolated)."""
    assert_user_access(principal, user_id)
    return {
        "user_id": user_id,
        "turns_count": len(session_store.get_history(user_id)),
        "messages": session_store.get_history(user_id),
    }


@router.delete("/chat/history/{user_id}", tags=["Multi-Agent Orchestration"])
async def clear_chat_history_endpoint(
    user_id: str,
    principal: Principal = Depends(get_current_principal),
) -> dict[str, Any]:
    """Clear conversational history for the given user_id (tenant-isolated)."""
    assert_user_access(principal, user_id)
    session_store.clear(user_id=user_id)
    return {
        "status": "cleared",
        "user_id": user_id,
    }


@router.get("/health", response_model=HealthResponse, tags=["Operations & Observability"])
async def health_endpoint() -> HealthResponse:
    """Liveness and readiness probe checking API status and ChromaDB vector store availability."""
    store = get_vector_store()
    chunks_count = store.ensure_initialized(include_live_scrape=False)
    llm_mode = "openai" if settings.use_live_llm else "deterministic_grounded"
    active_model = settings.openai_model if settings.use_live_llm else "deterministic-grounded"
    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        version=settings.app_version,
        vector_store_ready=chunks_count > 0,
        vector_store_chunks=chunks_count,
        llm_mode=llm_mode,
        langsmith_enabled=settings.langsmith_enabled,
        model=active_model,
    )


@router.get("/metrics", tags=["Operations & Observability"])
async def metrics_endpoint(
    _principal: Principal = Depends(require_roles("operator", "admin")),
) -> dict[str, Any]:
    """Return aggregated request latencies, agent/tool counters, and guardrail/handoff stats."""
    return trace_recorder.get_metrics()


@router.get("/alerts", tags=["Operations & Observability"])
async def alerts_endpoint(
    limit: int = Query(default=50, ge=1, le=500),
    alert_type: str | None = Query(default=None),
    _principal: Principal = Depends(require_roles("operator", "admin")),
) -> dict[str, Any]:
    """Return triggered SLO latency, security guardrail, and human handoff alerts."""
    alerts = trace_recorder.list_alerts(limit=limit, alert_type=alert_type)
    return {
        "count": len(alerts),
        "alerts": [a.model_dump() for a in alerts],
    }


@router.get("/traces", tags=["Operations & Observability"])
async def list_traces_endpoint(
    limit: int = Query(default=25, ge=1, le=200),
    _principal: Principal = Depends(require_roles("operator", "admin")),
) -> dict[str, Any]:
    """List recent end-to-end execution traces."""
    traces = trace_recorder.list_traces(limit=limit)
    return {
        "count": len(traces),
        "traces": [t.model_dump() for t in traces],
    }


@router.get("/traces/{trace_id}", tags=["Operations & Observability"])
async def get_trace_endpoint(
    trace_id: str,
    _principal: Principal = Depends(require_roles("operator", "admin")),
) -> dict[str, Any]:
    """Retrieve a detailed execution trace and all its agent/tool spans by trace_id."""
    trace = trace_recorder.get_trace(trace_id)
    if trace is None:
        raise HTTPException(
            status_code=404,
            detail=f"Trace '{trace_id}' not found.",
        )
    return trace.model_dump()


@router.post("/evals/run", tags=["Operations & Observability"])
async def run_evals_endpoint(
    payload: EvalRunRequest | None = None,
    sync_langsmith: bool = Query(
        default=False,
        description="Sync dataset and execute LangSmith evaluation experiment.",
    ),
    max_scenarios: int | None = Query(
        default=None,
        ge=1,
        le=50,
        description="Optional limit on number of scenarios to evaluate.",
    ),
    principal: Principal = Depends(require_roles("operator", "admin")),
) -> dict[str, Any]:
    """Execute the automated evaluation benchmark across challenge scenarios and return evaluation scorecard."""
    from scripts.evaluate import evaluate_dataset

    rate_limiter.check_and_consume(f"{principal.role}:{principal.user_id}")
    should_sync = (payload.sync_langsmith if payload is not None else False) or sync_langsmith
    limit = (
        payload.max_scenarios
        if payload is not None and payload.max_scenarios is not None
        else max_scenarios
    )
    return evaluate_dataset(sync_langsmith=should_sync, max_scenarios=limit)


@router.get("/handoffs", tags=["Human-in-the-Loop (HITL)"])
async def list_handoffs_endpoint(
    status: Literal["pending_human_review", "resolved"] | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    _principal: Principal = Depends(require_roles("operator", "admin")),
) -> dict[str, Any]:
    """List pending or resolved HITL escalation checkpoints (operator/admin only)."""
    records = [HandoffSummary(**item).model_dump() for item in handoff_store.list_handoffs(status=status, limit=limit)]
    return {"count": len(records), "handoffs": records}


@router.post("/handoffs/{thread_id}/resume", response_model=ChatResponse, tags=["Human-in-the-Loop (HITL)"])
async def resume_handoff_endpoint(
    thread_id: str,
    payload: HandoffResumeRequest,
    principal: Principal = Depends(require_roles("operator", "admin")),
) -> ChatResponse:
    """Resume a paused LangGraph HITL checkpoint with specialist decision and guidance."""
    try:
        result = resume_orchestration(
            thread_id,
            decision=payload.decision,
            operator_id=principal.user_id,
            operator_note=payload.operator_note,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ChatResponse(**result)


@router.get("/", response_class=HTMLResponse, tags=["Visual Explainer"])
@router.get("/dashboard", response_class=HTMLResponse, tags=["Visual Explainer"])
async def dashboard_endpoint(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
) -> HTMLResponse:
    """Serve the interactive Visual Explainer & Live Observability Dashboard (operator/admin only)."""
    try:
        principal = get_current_principal(request=request, credentials=credentials)
    except HTTPException as exc:
        accept = (request.headers.get("accept") or "").lower()
        if exc.status_code == 401 and "text/html" in accept:
            return HTMLResponse(content=DASHBOARD_LOGIN_HTML, status_code=401)
        raise

    if principal.role not in ("operator", "admin"):
        raise HTTPException(
            status_code=403,
            detail=f"Role '{principal.role}' is not authorized for this resource.",
        )
    return HTMLResponse(content=DASHBOARD_HTML, status_code=200)


STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
FAVICON_ICO_PATH = STATIC_DIR / "favicon.ico"
FAVICON_SVG_PATH = STATIC_DIR / "favicon.svg"
FAVICON_PNG_PATH = STATIC_DIR / "favicon.png"


@router.get("/favicon.ico", include_in_schema=False)
async def favicon_ico_endpoint() -> FileResponse:
    """Serve the application favicon in ICO format."""
    if FAVICON_ICO_PATH.exists():
        return FileResponse(
            FAVICON_ICO_PATH,
            media_type="image/x-icon",
            headers={"Cache-Control": "public, max-age=86400"},
        )
    return FileResponse(
        FAVICON_SVG_PATH,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/favicon.svg", include_in_schema=False)
async def favicon_svg_endpoint() -> FileResponse:
    """Serve crisp vector favicon.svg for modern browsers."""
    if FAVICON_SVG_PATH.exists():
        return FileResponse(
            FAVICON_SVG_PATH,
            media_type="image/svg+xml",
            headers={"Cache-Control": "public, max-age=86400"},
        )
    raise HTTPException(status_code=404, detail="Favicon SVG not found")


@router.get("/favicon.png", include_in_schema=False)
async def favicon_png_endpoint() -> FileResponse:
    """Serve high-resolution favicon.png."""
    if FAVICON_PNG_PATH.exists():
        return FileResponse(
            FAVICON_PNG_PATH,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=86400"},
        )
    raise HTTPException(status_code=404, detail="Favicon PNG not found")

