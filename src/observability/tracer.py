"""Execution trace recorder, metrics aggregator, and SLO/security alerting engine."""

from __future__ import annotations

import functools
import json
import math
import time
import uuid
from collections import Counter, deque
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Literal, TypeVar

from pydantic import BaseModel, Field

from src.config.settings import settings
from src.observability.logger import bind_trace_context, clear_trace_context, get_logger

try:
    from langsmith import traceable as _langsmith_traceable
except Exception:  # pragma: no cover
    _langsmith_traceable = None

logger = get_logger("observability.tracer")

F = TypeVar("F", bound=Callable[..., Any])


def traceable_step(
    name: str | None = None,
    run_type: str = "chain",
    metadata: dict[str, Any] | None = None,
) -> Callable[[F], F]:
    """Decorate a function with LangSmith @traceable when available, remaining a safe no-op offline."""

    def decorator(func: F) -> F:
        if _langsmith_traceable is not None and settings.langsmith_enabled:
            wrapped = _langsmith_traceable(
                name=name or func.__name__,
                run_type=run_type,
                metadata=metadata or {},
            )(func)
            return functools.wraps(func)(wrapped)  # type: ignore[return-value]
        return func

    return decorator


class TraceSpan(BaseModel):
    """Represents a single execution span (agent node, tool invocation, or guardrail check)."""

    span_id: str = Field(default_factory=lambda: f"span-{uuid.uuid4().hex[:10]}")
    name: str
    agent: str = "system"
    span_type: Literal["agent", "tool", "guardrail", "orchestration"] = "agent"
    start_time: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    end_time: str | None = None
    latency_ms: float = 0.0
    status: Literal["ok", "error", "blocked"] = "ok"
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    token_usage: dict[str, int] = Field(default_factory=dict)
    error: str | None = None


class AlertEvent(BaseModel):
    """Structured production alert triggered by SLO latency breach, security guardrail, or handoff."""

    alert_id: str = Field(default_factory=lambda: f"alt-{uuid.uuid4().hex[:10]}")
    trace_id: str
    user_id: str
    alert_type: Literal[
        "HIGH_LATENCY_ALERT",
        "SECURITY_GUARDRAIL_ALERT",
        "HUMAN_HANDOFF_ALERT",
    ]
    severity: Literal["info", "warning", "critical"]
    message: str
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    details: dict[str, Any] = Field(default_factory=dict)


class ExecutionTrace(BaseModel):
    """End-to-end execution trace for a single user request across the multi-agent graph."""

    trace_id: str = Field(default_factory=lambda: f"trc-{uuid.uuid4().hex[:12]}")
    user_id: str
    message: str
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    total_latency_ms: float = 0.0
    routed_agents: list[str] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    confidence_score: float = 1.0
    guardrail_triggered: bool = False
    handoff_required: bool = False
    status: Literal["completed", "blocked", "escalated", "error"] = "completed"
    final_response: str = ""
    effective_slo_target_ms: float = 7000.0
    slo_tier: Literal["fast_path", "complex_path"] = "fast_path"
    slo_violated: bool = False
    spans: list[TraceSpan] = Field(default_factory=list)
    alerts: list[AlertEvent] = Field(default_factory=list)
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0


class SpanHandle:
    """Mutable handle yielded inside `record_span` so callers can attach outputs and token usage."""

    def __init__(self, span: TraceSpan) -> None:
        self.span = span

    def set_output(self, **kwargs: Any) -> None:
        """Record key-value outputs on the active span."""
        self.span.outputs.update(kwargs)

    def set_metadata(self, **kwargs: Any) -> None:
        """Record key-value metadata on the active span."""
        self.span.metadata.update(kwargs)

    def set_tokens(
        self,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int | None = None,
    ) -> None:
        """Attach LLM token usage metrics to the active span."""
        computed_total = (
            total_tokens
            if total_tokens is not None
            else (prompt_tokens + completion_tokens)
        )
        self.span.token_usage = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": computed_total,
        }

    def mark_blocked(self, reason: str) -> None:
        """Mark the span as blocked by a guardrail."""
        self.span.status = "blocked"
        self.span.metadata["block_reason"] = reason


def extract_token_usage(resp: Any) -> dict[str, int]:
    """Safely extract prompt, completion, and total tokens from LangChain ChatOpenAI responses."""
    usage = getattr(resp, "usage_metadata", None)
    if not usage and hasattr(resp, "response_metadata"):
        usage = resp.response_metadata.get("token_usage")
    if not usage and isinstance(resp, dict):
        usage = resp.get("usage_metadata") or resp.get("token_usage")
    if isinstance(usage, dict):
        p = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
        c = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
        t = int(usage.get("total_tokens") or (p + c))
        return {"prompt_tokens": p, "completion_tokens": c, "total_tokens": t}
    return {}


class TraceRecorder:
    """Thread-safe in-memory and JSONL trace store, metrics aggregator, and alerting monitor."""

    def __init__(
        self,
        trace_log_path: str | Path | None = None,
        max_in_memory: int | None = None,
        latency_slo_ms: float | None = None,
        confidence_threshold: float | None = None,
    ) -> None:
        self.trace_log_path = settings.resolve_path(
            str(trace_log_path or settings.trace_log_path)
        )
        self.max_in_memory = max_in_memory or settings.max_in_memory_traces
        self.latency_slo_ms = (
            latency_slo_ms
            if latency_slo_ms is not None
            else settings.latency_slo_threshold_ms
        )
        self.latency_slo_fast_ms = (
            latency_slo_ms
            if latency_slo_ms is not None
            else settings.latency_slo_fast_path_ms
        )
        self.latency_slo_complex_ms = (
            latency_slo_ms * 4.5
            if latency_slo_ms is not None
            else settings.latency_slo_complex_path_ms
        )
        self.confidence_threshold = (
            confidence_threshold
            if confidence_threshold is not None
            else settings.confidence_escalation_threshold
        )

        self._active_traces: dict[str, tuple[ExecutionTrace, float]] = {}
        self._traces: deque[ExecutionTrace] = deque(maxlen=self.max_in_memory)
        self._traces_by_id: dict[str, ExecutionTrace] = {}
        self._alerts: deque[AlertEvent] = deque(maxlen=self.max_in_memory)
        self._agent_counts: Counter[str] = Counter()
        self._tool_counts: Counter[str] = Counter()

    def create_trace(
        self,
        user_id: str,
        message: str,
        trace_id: str | None = None,
    ) -> ExecutionTrace:
        """Initialize and register a new ExecutionTrace."""
        resolved_id = trace_id or f"trc-{uuid.uuid4().hex[:12]}"
        trace = ExecutionTrace(
            trace_id=resolved_id,
            user_id=user_id,
            message=message,
        )
        self._active_traces[resolved_id] = (trace, time.perf_counter())
        bind_trace_context(trace_id=resolved_id, user_id=user_id)
        logger.info(
            "trace_started",
            agent="orchestrator",
            message_preview=message[:120],
        )
        return trace

    @contextmanager
    def record_span(
        self,
        trace_id: str,
        name: str,
        agent: str = "system",
        span_type: Literal["agent", "tool", "guardrail", "orchestration"] = "agent",
        inputs: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Iterator[SpanHandle]:
        """Record a timed execution span inside an active trace."""
        span = TraceSpan(
            name=name,
            agent=agent,
            span_type=span_type,
            inputs=inputs or {},
            metadata=metadata or {},
        )
        handle = SpanHandle(span)
        start = time.perf_counter()
        try:
            yield handle
        except Exception as exc:
            span.status = "error"
            span.error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            elapsed_ms = round((time.perf_counter() - start) * 1000.0, 2)
            span.latency_ms = elapsed_ms
            span.end_time = datetime.now(timezone.utc).isoformat()

            if span_type == "agent" and agent not in ("system", "orchestrator"):
                self._agent_counts[agent] += 1
            elif span_type == "tool":
                self._tool_counts[name] += 1

            active_entry = self._active_traces.get(trace_id)
            if active_entry is not None:
                active_entry[0].spans.append(span)
            elif trace_id in self._traces_by_id:
                self._traces_by_id[trace_id].spans.append(span)

            logger.info(
                "span_completed",
                agent=agent,
                span_name=name,
                span_type=span_type,
                status=span.status,
                latency_ms=elapsed_ms,
                token_usage=span.token_usage or None,
            )

    def finalize_trace(
        self,
        trace_id: str,
        *,
        routed_agents: list[str] | None = None,
        tools_used: list[str] | None = None,
        sources: list[str] | None = None,
        confidence_score: float = 1.0,
        guardrail_triggered: bool = False,
        handoff_required: bool = False,
        final_response: str = "",
        status: Literal["completed", "blocked", "escalated", "error"] | None = None,
        override_latency_ms: float | None = None,
    ) -> ExecutionTrace:
        """Complete an active trace, evaluate SLO/security alerts, and persist to JSONL."""
        active_entry = self._active_traces.pop(trace_id, None)
        if active_entry is not None:
            trace, start_perf = active_entry
            computed_latency = round((time.perf_counter() - start_perf) * 1000.0, 2)
        else:
            trace = self._traces_by_id.get(
                trace_id,
                ExecutionTrace(trace_id=trace_id, user_id="unknown", message=""),
            )
            computed_latency = trace.total_latency_ms

        trace.total_latency_ms = (
            round(float(override_latency_ms), 2)
            if override_latency_ms is not None
            else computed_latency
        )
        if routed_agents is not None:
            trace.routed_agents = list(dict.fromkeys(routed_agents))
        if tools_used is not None:
            trace.tools_used = list(dict.fromkeys(tools_used))
        if sources is not None:
            trace.sources = list(dict.fromkeys(sources))

        # Aggregate token usage across all recorded spans
        total_tok = sum(s.token_usage.get("total_tokens", 0) for s in trace.spans)
        prompt_tok = sum(s.token_usage.get("prompt_tokens", 0) for s in trace.spans)
        comp_tok = sum(s.token_usage.get("completion_tokens", 0) for s in trace.spans)
        trace.total_tokens = total_tok
        trace.prompt_tokens = prompt_tok
        trace.completion_tokens = comp_tok

        trace.confidence_score = round(float(confidence_score), 3)
        trace.guardrail_triggered = bool(guardrail_triggered)
        trace.handoff_required = bool(handoff_required)
        trace.final_response = final_response

        if status is not None:
            trace.status = status
        elif guardrail_triggered:
            trace.status = "blocked"
        elif handoff_required:
            trace.status = "escalated"
        else:
            trace.status = "completed"

        # Determine dynamic multi-tier SLO based on route complexity
        complex_tools = {"web_search_general", "fetch_weather_forecast", "fetch_currency_exchange_rate"}
        is_complex = (
            bool(set(trace.tools_used).intersection(complex_tools))
            or trace.handoff_required
            or "escalation_agent" in trace.routed_agents
            or len([a for a in trace.routed_agents if a in ("knowledge_agent", "customer_support_agent", "escalation_agent")]) > 1
        )
        if is_complex:
            trace.slo_tier = "complex_path"
            trace.effective_slo_target_ms = self.latency_slo_complex_ms
        else:
            trace.slo_tier = "fast_path"
            trace.effective_slo_target_ms = self.latency_slo_fast_ms

        trace.slo_violated = trace.total_latency_ms > trace.effective_slo_target_ms

        # Evaluate SLO and security alerting rules
        generated_alerts = self._evaluate_alerts(trace)
        trace.alerts.extend(generated_alerts)

        # Store in ring buffer and lookup map
        if len(self._traces) == self.max_in_memory:
            oldest = self._traces[0]
            self._traces_by_id.pop(oldest.trace_id, None)
        self._traces.append(trace)
        self._traces_by_id[trace.trace_id] = trace

        self._persist_trace_jsonl(trace)
        self._export_to_langfuse_if_enabled(trace)

        logger.info(
            "trace_finalized",
            agent="orchestrator",
            status=trace.status,
            latency_ms=trace.total_latency_ms,
            routed_agents=trace.routed_agents,
            tools_used=trace.tools_used,
            confidence_score=trace.confidence_score,
            guardrail_triggered=trace.guardrail_triggered,
            handoff_required=trace.handoff_required,
            alerts_triggered=len(generated_alerts),
        )
        clear_trace_context()
        return trace

    def _evaluate_alerts(self, trace: ExecutionTrace) -> list[AlertEvent]:
        """Evaluate the 3 production alerting rules against a completed trace."""
        triggered: list[AlertEvent] = []

        # 1. Latency SLO Breach (dynamically evaluated against effective multi-tier SLO)
        if trace.slo_violated:
            tier_label = "Deep Research / Complex Path" if trace.slo_tier == "complex_path" else "Fast Path"
            alert = AlertEvent(
                trace_id=trace.trace_id,
                user_id=trace.user_id,
                alert_type="HIGH_LATENCY_ALERT",
                severity="warning",
                message=(
                    f"Request latency {trace.total_latency_ms:.1f}ms exceeded "
                    f"{tier_label} SLO threshold of {trace.effective_slo_target_ms:.1f}ms."
                ),
                details={
                    "latency_ms": trace.total_latency_ms,
                    "slo_threshold_ms": trace.effective_slo_target_ms,
                    "slo_tier": trace.slo_tier,
                    "routed_agents": trace.routed_agents,
                },
            )
            triggered.append(alert)

        # 2. Guardrail Security Incident
        if trace.guardrail_triggered:
            alert = AlertEvent(
                trace_id=trace.trace_id,
                user_id=trace.user_id,
                alert_type="SECURITY_GUARDRAIL_ALERT",
                severity="critical",
                message="Input/Output safety guardrail intercepted a potentially unsafe or prompt-injection request.",
                details={
                    "message_preview": trace.message[:120],
                    "status": trace.status,
                },
            )
            triggered.append(alert)

        # 3. Human Escalation / Low Confidence Spike
        if trace.handoff_required or trace.confidence_score < self.confidence_threshold:
            alert = AlertEvent(
                trace_id=trace.trace_id,
                user_id=trace.user_id,
                alert_type="HUMAN_HANDOFF_ALERT",
                severity="info",
                message=(
                    f"Request escalated to human specialist "
                    f"(confidence={trace.confidence_score:.2f}, handoff_required={trace.handoff_required})."
                ),
                details={
                    "confidence_score": trace.confidence_score,
                    "threshold": self.confidence_threshold,
                    "handoff_required": trace.handoff_required,
                },
            )
            triggered.append(alert)

        for alert in triggered:
            self._alerts.append(alert)
            logger.warning(
                "production_alert_triggered",
                agent="alerting_engine",
                alert_id=alert.alert_id,
                alert_type=alert.alert_type,
                severity=alert.severity,
                alert_message=alert.message,
            )

        return triggered

    def _persist_trace_jsonl(self, trace: ExecutionTrace) -> None:
        """Append serialized trace JSON line to local log file."""
        try:
            self.trace_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.trace_log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(trace.model_dump(), ensure_ascii=False) + "\n")
        except Exception as exc:  # pragma: no cover
            logger.error(
                "trace_persistence_failed",
                agent="observability",
                error=str(exc),
            )

    def _export_to_langfuse_if_enabled(self, trace: ExecutionTrace) -> None:
        """Export trace payload to Langfuse when LANGFUSE_ENABLED is configured."""
        if not (
            settings.langfuse_enabled
            and settings.langfuse_public_key
            and settings.langfuse_secret_key
        ):
            return
        try:  # pragma: no cover
            from langfuse import Langfuse  # type: ignore[import-not-found]

            client = Langfuse(
                public_key=settings.langfuse_public_key,
                secret_key=settings.langfuse_secret_key,
                host=settings.langfuse_host,
            )
            lf_trace = client.trace(
                id=trace.trace_id,
                user_id=trace.user_id,
                input=trace.message,
                output=trace.final_response,
                metadata={
                    "routed_agents": trace.routed_agents,
                    "tools_used": trace.tools_used,
                    "confidence_score": trace.confidence_score,
                },
            )
            for span in trace.spans:
                lf_trace.span(
                    name=span.name,
                    input=span.inputs,
                    output=span.outputs,
                    metadata=span.metadata,
                )
        except Exception as exc:  # pragma: no cover
            logger.warning("langfuse_export_skipped", error=str(exc))

    def get_trace(self, trace_id: str) -> ExecutionTrace | None:
        """Retrieve a trace by ID from memory or fallback to the local JSONL store."""
        if trace_id in self._traces_by_id:
            return self._traces_by_id[trace_id]
        if trace_id in self._active_traces:
            return self._active_traces[trace_id][0]
        if self.trace_log_path.exists():
            try:
                with self.trace_log_path.open("r", encoding="utf-8") as handle:
                    for line in reversed(handle.readlines()):
                        line = line.strip()
                        if not line:
                            continue
                        data = json.loads(line)
                        if data.get("trace_id") == trace_id:
                            return ExecutionTrace.model_validate(data)
            except Exception:  # pragma: no cover
                return None
        return None

    def list_traces(self, limit: int = 50) -> list[ExecutionTrace]:
        """Return the most recent traces (newest first)."""
        items = list(self._traces)
        items.reverse()
        return items[: max(1, limit)]

    def list_alerts(
        self,
        limit: int = 50,
        alert_type: str | None = None,
    ) -> list[AlertEvent]:
        """Return recent production alerts (newest first), optionally filtered by type."""
        items = list(self._alerts)
        items.reverse()
        if alert_type:
            items = [a for a in items if a.alert_type == alert_type]
        return items[: max(1, limit)]

    def get_metrics(self) -> dict[str, Any]:
        """Aggregate operational metrics across all recorded traces."""
        traces = list(self._traces)
        total = len(traces)
        latencies = sorted(t.total_latency_ms for t in traces)
        avg_latency = round(sum(latencies) / total, 2) if total > 0 else 0.0
        if total > 0:
            p95_idx = min(total - 1, max(0, math.ceil(0.95 * total) - 1))
            p95_latency = round(latencies[p95_idx], 2)
        else:
            p95_latency = 0.0

        guardrail_blocks = sum(1 for t in traces if t.guardrail_triggered)
        human_handoffs = sum(1 for t in traces if t.handoff_required)
        total_tokens_consumed = sum(t.total_tokens for t in traces)

        alerts_by_type: Counter[str] = Counter(a.alert_type for a in self._alerts)

        return {
            "total_requests": total,
            "average_latency_ms": avg_latency,
            "p95_latency_ms": p95_latency,
            "guardrail_blocks": guardrail_blocks,
            "human_handoffs": human_handoffs,
            "total_tokens_consumed": total_tokens_consumed,
            "agent_invocation_counts": dict(self._agent_counts),
            "tool_invocation_counts": dict(self._tool_counts),
            "alerts_count": len(self._alerts),
            "alerts_by_type": dict(alerts_by_type),
            "langsmith_enabled": settings.langsmith_enabled,
            "langfuse_enabled": settings.langfuse_enabled,
        }

    def reset(self) -> None:
        """Clear in-memory traces, alerts, and counters (used in isolated tests)."""
        self._active_traces.clear()
        self._traces.clear()
        self._traces_by_id.clear()
        self._alerts.clear()
        self._agent_counts.clear()
        self._tool_counts.clear()


trace_recorder = TraceRecorder()
