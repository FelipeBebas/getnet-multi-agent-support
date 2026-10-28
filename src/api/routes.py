"""FastAPI HTTP endpoints for multi-agent chat, health probes, metrics, traces, alerts, and dashboard."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse

from src.api.dashboard import DASHBOARD_HTML
from src.api.schemas import ChatRequest, ChatResponse, EvalRunRequest, HealthResponse
from src.config.settings import settings
from src.observability.tracer import trace_recorder
from src.orchestration.graph import execute_orchestration, execute_orchestration_stream
from src.orchestration.session_store import session_store
from src.rag.vector_store import get_vector_store

router = APIRouter()


@router.post("/chat", response_model=ChatResponse, tags=["Multi-Agent Orchestration"])
@router.post("/", response_model=ChatResponse, tags=["Multi-Agent Orchestration"])
@router.post("/api/v1/message", response_model=ChatResponse, tags=["Multi-Agent Orchestration"])
async def chat_endpoint(payload: ChatRequest) -> ChatResponse:
    """Process an incoming user message through the 5-agent LangGraph orchestration."""
    result = execute_orchestration(
        message=payload.message,
        user_id=payload.user_id,
    )
    return ChatResponse(**result)


@router.post("/chat/stream", tags=["Multi-Agent Orchestration"])
async def chat_stream_endpoint(payload: ChatRequest) -> StreamingResponse:
    """Stream multi-agent orchestration events and real-time LLM token generation via Server-Sent Events (SSE)."""

    async def event_generator():
        async for event in execute_orchestration_stream(
            message=payload.message,
            user_id=payload.user_id,
        ):
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
async def get_chat_history_endpoint(user_id: str) -> dict[str, Any]:
    """Retrieve in-memory conversational history for the given user_id."""
    return {
        "user_id": user_id,
        "turns_count": len(session_store.get_history(user_id)),
        "messages": session_store.get_history(user_id),
    }


@router.delete("/chat/history/{user_id}", tags=["Multi-Agent Orchestration"])
async def clear_chat_history_endpoint(user_id: str) -> dict[str, Any]:
    """Clear in-memory conversational history for the given user_id."""
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
async def metrics_endpoint() -> dict[str, Any]:
    """Return aggregated request latencies, agent/tool counters, and guardrail/handoff stats."""
    return trace_recorder.get_metrics()


@router.get("/alerts", tags=["Operations & Observability"])
async def alerts_endpoint(
    limit: int = Query(default=50, ge=1, le=500),
    alert_type: str | None = Query(default=None),
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
) -> dict[str, Any]:
    """List recent end-to-end execution traces."""
    traces = trace_recorder.list_traces(limit=limit)
    return {
        "count": len(traces),
        "traces": [t.model_dump() for t in traces],
    }


@router.get("/traces/{trace_id}", tags=["Operations & Observability"])
async def get_trace_endpoint(trace_id: str) -> dict[str, Any]:
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
) -> dict[str, Any]:
    """Execute the automated evaluation benchmark across challenge scenarios and return evaluation scorecard."""
    from scripts.evaluate import evaluate_dataset

    should_sync = (payload.sync_langsmith if payload is not None else False) or sync_langsmith
    limit = (
        payload.max_scenarios
        if payload is not None and payload.max_scenarios is not None
        else max_scenarios
    )
    return evaluate_dataset(sync_langsmith=should_sync, max_scenarios=limit)


@router.get("/", response_class=HTMLResponse, tags=["Visual Explainer"])
@router.get("/dashboard", response_class=HTMLResponse, tags=["Visual Explainer"])
async def dashboard_endpoint() -> HTMLResponse:
    """Serve the interactive Visual Explainer & Live Observability Dashboard."""
    return HTMLResponse(content=DASHBOARD_HTML, status_code=200)
