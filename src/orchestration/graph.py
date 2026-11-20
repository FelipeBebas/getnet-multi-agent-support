"""LangGraph StateGraph builder and execution runner for the 5-agent Getnet orchestration."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, AsyncGenerator

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from src.agents.escalation_agent import run_escalation_agent
from src.agents.knowledge_agent import run_knowledge_agent
from src.agents.personality_agent import run_personality_agent
from src.agents.router_agent import classify_and_route
from src.agents.support_agent import run_customer_support_agent
from src.config.settings import settings
from src.guardrails.validator import (
    sanitize_output_message,
    validate_input_message,
)
from src.observability.logger import get_logger
from src.observability.tracer import trace_recorder, traceable_step
from src.orchestration.persistence import handoff_store
from src.orchestration.session_store import session_store
from src.orchestration.state import OrchestrationState

logger = get_logger("orchestration.graph")


def _input_guardrail_node(state: OrchestrationState) -> OrchestrationState:
    trace_id = state["trace_id"]
    message = state["message"]

    with trace_recorder.record_span(
        trace_id=trace_id,
        name="validate_input_message",
        agent="input_guardrail",
        span_type="guardrail",
        inputs={"message_preview": message[:120]},
    ) as span:
        result = validate_input_message(message)
        span.set_output(
            allowed=result.allowed,
            violation_category=result.violation_category,
            matched_rule=result.matched_rule,
        )
        if not result.allowed:
            span.mark_blocked(result.reason)

    if not result.allowed:
        return {
            "guardrail_triggered": True,
            "guardrail_reason": result.reason,
            "final_response": result.safe_refusal_message,
            "confidence_score": 1.0,
            "routed_agents": ["input_guardrail"],
        }

    return {
        "guardrail_triggered": False,
        "guardrail_reason": "",
    }


def _router_agent_node(state: OrchestrationState) -> OrchestrationState:
    trace_id = state["trace_id"]
    message = state["message"]
    user_id = state["user_id"]
    chat_history = state.get("chat_history") or []

    with trace_recorder.record_span(
        trace_id=trace_id,
        name="router_classify_and_plan",
        agent="router_agent",
        span_type="agent",
        inputs={"message": message, "user_id": user_id, "chat_history_len": len(chat_history)},
    ) as span:
        plan = classify_and_route(
            message=message, user_id=user_id, chat_history=chat_history
        )
        rewritten = plan.rewritten_query or message
        if plan.token_usage:
            span.set_tokens(
                prompt_tokens=plan.token_usage.get("prompt_tokens", 0),
                completion_tokens=plan.token_usage.get("completion_tokens", 0),
                total_tokens=plan.token_usage.get("total_tokens", 0),
            )
        span.set_output(
            primary_intent=plan.primary_intent,
            agent_queue=plan.agent_queue,
            knowledge_sub_intent=plan.knowledge_sub_intent,
            support_sub_intent=plan.support_sub_intent,
            confidence=plan.confidence,
            rewritten_query=rewritten,
        )

    routed = list(state.get("routed_agents") or [])
    routed.append("router_agent")

    return {
        "router_plan": plan.model_dump(),
        "agent_queue": list(plan.agent_queue),
        "language": plan.language,
        "routed_agents": routed,
        "confidence_score": plan.confidence,
        "rewritten_query": rewritten,
    }


def _knowledge_agent_node(state: OrchestrationState) -> OrchestrationState:
    trace_id = state["trace_id"]
    message = state.get("rewritten_query") or state["message"]
    chat_history = state.get("chat_history") or []
    plan = state.get("router_plan") or {}
    sub_intent = str(plan.get("knowledge_sub_intent") or "product_rag")

    queue = [a for a in (state.get("agent_queue") or []) if a != "knowledge_agent"]

    with trace_recorder.record_span(
        trace_id=trace_id,
        name="knowledge_agent_execute",
        agent="knowledge_agent",
        span_type="agent",
        inputs={"message": message, "sub_intent": sub_intent},
    ) as span:
        step_out = run_knowledge_agent(
            message=message, sub_intent=sub_intent, chat_history=chat_history
        )
        if step_out.token_usage:
            span.set_tokens(
                prompt_tokens=step_out.token_usage.get("prompt_tokens", 0),
                completion_tokens=step_out.token_usage.get("completion_tokens", 0),
                total_tokens=step_out.token_usage.get("total_tokens", 0),
            )
        span.set_output(
            tools_used=step_out.tools_used,
            sources=step_out.sources,
            confidence=step_out.confidence,
        )

    for tool_name in step_out.tools_used:
        with trace_recorder.record_span(
            trace_id=trace_id,
            name=tool_name,
            agent="knowledge_agent",
            span_type="tool",
            inputs={"query": message},
        ) as t_span:
            t_span.set_output(sources=step_out.sources)

    routed = list(state.get("routed_agents") or [])
    routed.append("knowledge_agent")

    outputs = list(state.get("agent_outputs") or [])
    outputs.append(step_out.model_dump())

    tools = list(state.get("tools_used") or [])
    tools.extend(step_out.tools_used)

    sources = list(state.get("sources") or [])
    sources.extend(step_out.sources)

    prev_conf = float(state.get("confidence_score") or 1.0)
    combined_conf = round(min(prev_conf, step_out.confidence), 3)

    return {
        "agent_queue": queue,
        "routed_agents": routed,
        "agent_outputs": outputs,
        "tools_used": list(dict.fromkeys(tools)),
        "sources": list(dict.fromkeys(sources)),
        "confidence_score": combined_conf,
    }


def _customer_support_agent_node(state: OrchestrationState) -> OrchestrationState:
    trace_id = state["trace_id"]
    message = state.get("rewritten_query") or state["message"]
    user_id = state["user_id"]
    chat_history = state.get("chat_history") or []
    plan = state.get("router_plan") or {}
    sub_intent = str(plan.get("support_sub_intent") or "all")

    queue = [a for a in (state.get("agent_queue") or []) if a != "customer_support_agent"]

    with trace_recorder.record_span(
        trace_id=trace_id,
        name="customer_support_agent_execute",
        agent="customer_support_agent",
        span_type="agent",
        inputs={"message": message, "user_id": user_id, "sub_intent": sub_intent},
    ) as span:
        step_out = run_customer_support_agent(
            message=message,
            user_id=user_id,
            sub_intent=sub_intent,
            chat_history=chat_history,
        )
        if step_out.token_usage:
            span.set_tokens(
                prompt_tokens=step_out.token_usage.get("prompt_tokens", 0),
                completion_tokens=step_out.token_usage.get("completion_tokens", 0),
                total_tokens=step_out.token_usage.get("total_tokens", 0),
            )
        span.set_output(
            tools_used=step_out.tools_used,
            sources=step_out.sources,
            confidence=step_out.confidence,
        )

    for tool_name in step_out.tools_used:
        with trace_recorder.record_span(
            trace_id=trace_id,
            name=tool_name,
            agent="customer_support_agent",
            span_type="tool",
            inputs={"user_id": user_id, "sub_intent": sub_intent},
        ) as t_span:
            t_span.set_output(sources=step_out.sources)

    routed = list(state.get("routed_agents") or [])
    routed.append("customer_support_agent")

    outputs = list(state.get("agent_outputs") or [])
    outputs.append(step_out.model_dump())

    tools = list(state.get("tools_used") or [])
    tools.extend(step_out.tools_used)

    sources = list(state.get("sources") or [])
    sources.extend(step_out.sources)

    prev_conf = float(state.get("confidence_score") or 1.0)
    combined_conf = round(min(prev_conf, step_out.confidence), 3)

    return {
        "agent_queue": queue,
        "routed_agents": routed,
        "agent_outputs": outputs,
        "tools_used": list(dict.fromkeys(tools)),
        "sources": list(dict.fromkeys(sources)),
        "confidence_score": combined_conf,
    }


def _escalation_agent_node(state: OrchestrationState) -> OrchestrationState:
    trace_id = state["trace_id"]
    thread_id = str(state.get("thread_id") or f"thr-{trace_id}")
    message = state["message"]
    user_id = state["user_id"]
    current_conf = float(state.get("confidence_score") or 0.48)
    plan = state.get("router_plan") or {}
    risk_tier = str(plan.get("risk_tier") or "high")

    queue = [a for a in (state.get("agent_queue") or []) if a != "escalation_agent"]

    reason = (
        "Epistemic uncertainty: unverified out-of-corpus knowledge or low confidence threshold (< 0.60)"
        if current_conf < settings.confidence_escalation_threshold
        else "Explicit human specialist request or complex policy escalation"
    )

    existing = handoff_store.get(thread_id)
    if existing is None:
        with trace_recorder.record_span(
            trace_id=trace_id,
            name="escalation_agent_execute",
            agent="escalation_agent",
            span_type="agent",
            inputs={"message": message, "user_id": user_id, "reason": reason, "thread_id": thread_id},
        ) as span:
            initial_step = run_escalation_agent(
                message=message,
                user_id=user_id,
                reason=reason,
                confidence_score=min(current_conf, 0.48),
            )
            span.set_output(
                tools_used=initial_step.tools_used,
                handoff_required=True,
                handoff_status="pending_human_review",
            )

        for tool_name in initial_step.tools_used:
            with trace_recorder.record_span(
                trace_id=trace_id,
                name=tool_name,
                agent="escalation_agent",
                span_type="tool",
                inputs={"user_id": user_id, "thread_id": thread_id},
            ) as t_span:
                t_span.set_output(handoff_required=True)

        handoff_meta = (initial_step.raw_data or {}).get("handoff") or {}
        ticket_meta = ((initial_step.raw_data or {}).get("ticket") or {}).get("created_ticket") or {}
        protocol_id = str(handoff_meta.get("protocol_id") or "ESC-GN-PENDING")
        ticket_id = str(ticket_meta.get("ticket_id") or "TCK-2026-ESC")
        handoff_store.upsert_pending(
            thread_id=thread_id,
            trace_id=trace_id,
            user_id=user_id,
            protocol_id=protocol_id,
            ticket_id=ticket_id,
            risk_tier=risk_tier,
            reason=reason,
            message_preview=message[:200],
        )
    else:
        protocol_id = str(existing["protocol_id"])
        ticket_id = str(existing["ticket_id"])

    # Suspend graph execution via native LangGraph interrupt() until an operator resumes via Command(resume=...)
    decision_raw = interrupt(
        {
            "thread_id": thread_id,
            "user_id": user_id,
            "protocol_id": protocol_id,
            "ticket_id": ticket_id,
            "risk_tier": risk_tier,
            "reason": reason,
            "handoff_status": "pending_human_review",
        }
    )
    decision_dict = (
        dict(decision_raw)
        if isinstance(decision_raw, dict)
        else {"decision": "approved", "operator_note": str(decision_raw), "operator_id": "operator"}
    )

    resolved_step = run_escalation_agent(
        message=message,
        user_id=user_id,
        reason=reason,
        confidence_score=min(current_conf, 0.48),
        human_decision=decision_dict,
        existing_protocol_id=protocol_id,
        existing_ticket_id=ticket_id,
    )

    routed = list(state.get("routed_agents") or [])
    if "escalation_agent" not in routed:
        routed.append("escalation_agent")

    outputs = list(state.get("agent_outputs") or [])
    outputs.append(resolved_step.model_dump())

    tools = list(state.get("tools_used") or [])
    tools.extend(resolved_step.tools_used)

    sources = list(state.get("sources") or [])
    sources.extend(resolved_step.sources)

    return {
        "agent_queue": queue,
        "routed_agents": routed,
        "agent_outputs": outputs,
        "tools_used": list(dict.fromkeys(tools)),
        "sources": list(dict.fromkeys(sources)),
        "confidence_score": resolved_step.confidence,
        "handoff_required": True,
        "handoff_status": "resolved",
        "thread_id": thread_id,
        "human_decision": decision_dict,
        "escalation_details": resolved_step.raw_data,
    }


def _personality_agent_node(state: OrchestrationState) -> OrchestrationState:
    trace_id = state["trace_id"]
    message = state.get("rewritten_query") or state["message"]
    user_id = state["user_id"]
    chat_history = state.get("chat_history") or []
    language = str(state.get("language") or "en")
    handoff_required = bool(state.get("handoff_required", False))
    agent_outputs = list(state.get("agent_outputs") or [])

    with trace_recorder.record_span(
        trace_id=trace_id,
        name="personality_agent_synthesize",
        agent="personality_agent",
        span_type="agent",
        inputs={
            "upstream_agents_count": len(agent_outputs),
            "language": language,
            "handoff_required": handoff_required,
            "chat_history_len": len(chat_history),
        },
    ) as span:
        synthesized, token_usage = run_personality_agent(
            message=message,
            user_id=user_id,
            agent_outputs=agent_outputs,
            language=language,
            handoff_required=handoff_required,
            chat_history=chat_history,
        )
        if token_usage:
            span.set_tokens(
                prompt_tokens=token_usage.get("prompt_tokens", 0),
                completion_tokens=token_usage.get("completion_tokens", 0),
                total_tokens=token_usage.get("total_tokens", 0),
            )
        span.set_output(response_length=len(synthesized))

    routed = list(state.get("routed_agents") or [])
    routed.append("personality_agent")

    return {
        "routed_agents": routed,
        "final_response": synthesized,
    }


def _output_guardrail_node(state: OrchestrationState) -> OrchestrationState:
    trace_id = state["trace_id"]
    raw_response = str(state.get("final_response") or "")

    with trace_recorder.record_span(
        trace_id=trace_id,
        name="sanitize_output_message",
        agent="output_guardrail",
        span_type="guardrail",
        inputs={"response_length": len(raw_response)},
    ) as span:
        sanitized = sanitize_output_message(raw_response)
        span.set_output(
            modified=sanitized.modified,
            redactions_applied=sanitized.redactions_applied,
        )

    return {
        "final_response": sanitized.sanitized_text,
    }


def _after_input_guardrail(state: OrchestrationState) -> str:
    if state.get("guardrail_triggered"):
        return "output_guardrail"
    return "router_agent"


def _dispatch_next_from_queue(state: OrchestrationState) -> str:
    plan = state.get("router_plan") or {}
    if plan.get("primary_intent") == "out_of_scope":
        return "personality_agent"

    queue = list(state.get("agent_queue") or [])
    if queue:
        next_agent = queue[0]
        if next_agent in ("knowledge_agent", "customer_support_agent", "escalation_agent"):
            return next_agent

    # Automatic confidence-based escalation check gated by business risk tier
    conf = float(state.get("confidence_score") or 1.0)
    routed = list(state.get("routed_agents") or [])
    risk_tier = str(plan.get("risk_tier") or "low")

    if conf < settings.confidence_escalation_threshold and "escalation_agent" not in routed:
        if risk_tier in ("high", "medium"):
            logger.warning(
                "orchestrator.escalating_low_confidence",
                confidence=conf,
                threshold=settings.confidence_escalation_threshold,
                risk_tier=risk_tier,
            )
            return "escalation_agent"

        logger.info(
            "orchestrator.escalation_suppressed_low_risk",
            confidence=conf,
            threshold=settings.confidence_escalation_threshold,
            risk_tier=risk_tier,
            reason="Informational low-risk query with epistemic uncertainty does not require human ticket.",
        )

    return "personality_agent"


def _build_checkpointer() -> Any:
    """Create the configured LangGraph checkpointer (SqliteSaver or MemorySaver)."""
    raw = str(settings.hitl_checkpoint_db_path or ":memory:").strip()
    if not raw or raw == ":memory:":
        return MemorySaver()
    resolved = settings.resolve_path(raw)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(resolved), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    return SqliteSaver(conn)


def build_orchestration_graph(checkpointer: Any | None = None) -> Any:
    """Construct and compile the 5-agent LangGraph StateGraph workflow with HITL checkpointing."""
    workflow = StateGraph(OrchestrationState)

    workflow.add_node("input_guardrail", _input_guardrail_node)
    workflow.add_node("router_agent", _router_agent_node)
    workflow.add_node("knowledge_agent", _knowledge_agent_node)
    workflow.add_node("customer_support_agent", _customer_support_agent_node)
    workflow.add_node("escalation_agent", _escalation_agent_node)
    workflow.add_node("personality_agent", _personality_agent_node)
    workflow.add_node("output_guardrail", _output_guardrail_node)

    workflow.add_edge(START, "input_guardrail")
    workflow.add_conditional_edges(
        "input_guardrail",
        _after_input_guardrail,
        {
            "router_agent": "router_agent",
            "output_guardrail": "output_guardrail",
        },
    )

    routing_map = {
        "knowledge_agent": "knowledge_agent",
        "customer_support_agent": "customer_support_agent",
        "escalation_agent": "escalation_agent",
        "personality_agent": "personality_agent",
    }
    workflow.add_conditional_edges("router_agent", _dispatch_next_from_queue, routing_map)
    workflow.add_conditional_edges("knowledge_agent", _dispatch_next_from_queue, routing_map)
    workflow.add_conditional_edges(
        "customer_support_agent", _dispatch_next_from_queue, routing_map
    )

    workflow.add_edge("escalation_agent", "personality_agent")
    workflow.add_edge("personality_agent", "output_guardrail")
    workflow.add_edge("output_guardrail", END)

    resolved_cp = checkpointer if checkpointer is not None else _build_checkpointer()
    return workflow.compile(checkpointer=resolved_cp)


_compiled_graph: Any = None
_compiled_cp_target: str | None = None


def get_orchestration_graph() -> Any:
    """Return cached compiled LangGraph instance, rebuilding if checkpointer path changed."""
    global _compiled_graph, _compiled_cp_target
    target = str(settings.hitl_checkpoint_db_path or ":memory:")
    if _compiled_graph is None or _compiled_cp_target != target:
        _compiled_graph = build_orchestration_graph()
        _compiled_cp_target = target
    return _compiled_graph


def _format_pending_handoff_message(
    user_id: str,
    thread_id: str,
    interrupt_payload: dict[str, Any],
) -> str:
    """Format a safe merchant-facing message when execution pauses at interrupt()."""
    protocol_id = interrupt_payload.get("protocol_id", "ESC-GN-PENDING")
    ticket_id = interrupt_payload.get("ticket_id", "TCK-2026-ESC")
    reason = interrupt_payload.get("reason", "Human specialist verification requested.")
    raw = (
        f"Hello **{user_id}**, your request has been escalated for human specialist approval "
        f"(Status: `pending_human_review`, Thread: `{thread_id}`).\n\n"
        f"- **Escalation Protocol**: `{protocol_id}`\n"
        f"- **Support Ticket**: `{ticket_id}`\n"
        f"- **Reason**: {reason}\n\n"
        "Execution is paused awaiting specialist confirmation. Once reviewed, your response will resume automatically."
    )
    return sanitize_output_message(raw).sanitized_text


def _build_interrupted_result(
    *,
    trace_id: str,
    thread_id: str,
    user_id: str,
    message: str,
    state_snapshot: dict[str, Any],
    interrupt_payload: dict[str, Any],
) -> dict[str, Any]:
    """Finalize trace and build response dict when LangGraph hits interrupt()."""
    routed = list(state_snapshot.get("routed_agents") or [])
    if "escalation_agent" not in routed:
        routed.append("escalation_agent")
    tools = list(state_snapshot.get("tools_used") or [])
    for t_name in ("dispatch_human_handoff", "manage_support_ticket"):
        if t_name not in tools:
            tools.append(t_name)
    sources = list(state_snapshot.get("sources") or [])
    for src_name in (
        "Getnet Omnichannel Human Handoff Router",
        "Getnet Technical Support & Field Service CRM",
    ):
        if src_name not in sources:
            sources.append(src_name)

    pending_text = _format_pending_handoff_message(user_id, thread_id, interrupt_payload)
    conf = min(float(state_snapshot.get("confidence_score") or 0.48), 0.48)

    finalized_trace = trace_recorder.finalize_trace(
        trace_id,
        routed_agents=routed,
        tools_used=tools,
        sources=sources,
        confidence_score=conf,
        guardrail_triggered=False,
        handoff_required=True,
        final_response=pending_text,
        status="escalated",
    )

    session_store.add_message(user_id=user_id, role="user", content=message)
    session_store.add_message(
        user_id=user_id, role="assistant", content=finalized_trace.final_response
    )

    return {
        "response": finalized_trace.final_response,
        "user_id": user_id,
        "routed_agents": finalized_trace.routed_agents,
        "tools_used": finalized_trace.tools_used,
        "sources": finalized_trace.sources,
        "confidence_score": finalized_trace.confidence_score,
        "guardrail_triggered": False,
        "handoff_required": True,
        "handoff_status": "pending_human_review",
        "thread_id": thread_id,
        "human_decision": None,
        "trace_id": finalized_trace.trace_id,
        "latency_ms": finalized_trace.total_latency_ms,
        "effective_slo_target_ms": finalized_trace.effective_slo_target_ms,
        "slo_tier": finalized_trace.slo_tier,
        "slo_violated": finalized_trace.slo_violated,
        "total_tokens": finalized_trace.total_tokens,
        "prompt_tokens": finalized_trace.prompt_tokens,
        "completion_tokens": finalized_trace.completion_tokens,
        "router_plan": state_snapshot.get("router_plan") or {},
        "retrieved_contexts": _extract_retrieved_contexts(
            list(state_snapshot.get("agent_outputs") or [])
        )
        or [pending_text],
        "chat_history": session_store.get_history(user_id),
    }


def _extract_retrieved_contexts(agent_outputs: list[dict[str, Any]]) -> list[str]:
    """Collect retrieved RAG chunks, web snippets, or tool outputs as evaluation contexts."""
    contexts: list[str] = []
    for step in agent_outputs:
        raw = step.get("raw_data") or {}
        rag_block = raw.get("rag") or {}
        chunks = rag_block.get("chunks") or []
        for chunk in chunks:
            text = str(chunk.get("content") or "").strip()
            if text and text not in contexts:
                contexts.append(text)
        web_block = raw.get("web") or {}
        web_summary = str(web_block.get("summary") or "").strip()
        if web_summary and web_summary not in contexts:
            contexts.append(web_summary)
        if not chunks and not web_summary:
            content = str(step.get("content") or "").strip()
            if content and content not in contexts:
                contexts.append(content)
    return contexts


@traceable_step(name="getnet_multi_agent_orchestration", run_type="chain")
def execute_orchestration(
    message: str,
    user_id: str,
    trace_id: str | None = None,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """Run an incoming user request end-to-end through the LangGraph orchestration with checkpointing."""
    trace = trace_recorder.create_trace(
        user_id=user_id,
        message=message,
        trace_id=trace_id,
    )
    resolved_thread_id = thread_id or f"thr-{trace.trace_id}"

    initial_state: OrchestrationState = {
        "trace_id": trace.trace_id,
        "thread_id": resolved_thread_id,
        "user_id": user_id,
        "message": message,
        "language": "en",
        "guardrail_triggered": False,
        "guardrail_reason": "",
        "router_plan": {},
        "agent_queue": [],
        "routed_agents": [],
        "agent_outputs": [],
        "tools_used": [],
        "sources": [],
        "confidence_score": 1.0,
        "handoff_required": False,
        "handoff_status": "none",
        "human_decision": None,
        "escalation_details": None,
        "final_response": "",
        "chat_history": session_store.get_history(user_id),
        "rewritten_query": message,
    }

    graph = get_orchestration_graph()
    config = {"configurable": {"thread_id": resolved_thread_id}}
    final_state: dict[str, Any] = graph.invoke(initial_state, config=config)

    interrupts = final_state.get("__interrupt__")
    if interrupts:
        first_int = interrupts[0]
        int_val = getattr(first_int, "value", first_int)
        if not isinstance(int_val, dict):
            int_val = {"protocol_id": "ESC-GN-PENDING", "ticket_id": "TCK-2026-ESC"}
        return _build_interrupted_result(
            trace_id=trace.trace_id,
            thread_id=resolved_thread_id,
            user_id=user_id,
            message=message,
            state_snapshot=final_state,
            interrupt_payload=int_val,
        )

    finalized_trace = trace_recorder.finalize_trace(
        trace.trace_id,
        routed_agents=list(final_state.get("routed_agents") or []),
        tools_used=list(final_state.get("tools_used") or []),
        sources=list(final_state.get("sources") or []),
        confidence_score=float(final_state.get("confidence_score") or 1.0),
        guardrail_triggered=bool(final_state.get("guardrail_triggered", False)),
        handoff_required=bool(final_state.get("handoff_required", False)),
        final_response=str(final_state.get("final_response") or ""),
    )

    session_store.add_message(user_id=user_id, role="user", content=message)
    session_store.add_message(
        user_id=user_id, role="assistant", content=finalized_trace.final_response
    )

    return {
        "response": finalized_trace.final_response,
        "user_id": user_id,
        "routed_agents": finalized_trace.routed_agents,
        "tools_used": finalized_trace.tools_used,
        "sources": finalized_trace.sources,
        "confidence_score": finalized_trace.confidence_score,
        "guardrail_triggered": finalized_trace.guardrail_triggered,
        "handoff_required": finalized_trace.handoff_required,
        "handoff_status": str(final_state.get("handoff_status") or "none"),
        "thread_id": resolved_thread_id,
        "human_decision": final_state.get("human_decision"),
        "trace_id": finalized_trace.trace_id,
        "latency_ms": finalized_trace.total_latency_ms,
        "effective_slo_target_ms": finalized_trace.effective_slo_target_ms,
        "slo_tier": finalized_trace.slo_tier,
        "slo_violated": finalized_trace.slo_violated,
        "total_tokens": finalized_trace.total_tokens,
        "prompt_tokens": finalized_trace.prompt_tokens,
        "completion_tokens": finalized_trace.completion_tokens,
        "router_plan": final_state.get("router_plan") or {},
        "retrieved_contexts": _extract_retrieved_contexts(
            list(final_state.get("agent_outputs") or [])
        ),
        "chat_history": session_store.get_history(user_id),
    }


@traceable_step(name="getnet_hitl_resume", run_type="chain")
def resume_orchestration(
    thread_id: str,
    *,
    decision: str,
    operator_id: str,
    operator_note: str,
) -> dict[str, Any]:
    """Resume a paused HITL LangGraph checkpoint using Command(resume=...)."""
    existing = handoff_store.get(thread_id)
    if existing is None:
        raise KeyError(f"Handoff thread '{thread_id}' not found.")
    if existing.get("status") != "pending_human_review":
        raise ValueError(f"Handoff thread '{thread_id}' is already resolved.")

    user_id = str(existing["user_id"])
    resume_trace = trace_recorder.create_trace(
        user_id=user_id,
        message=f"[HITL RESUME {thread_id}] ({decision}): {operator_note}",
    )

    graph = get_orchestration_graph()
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = graph.get_state(config)
    if snapshot is None or not snapshot.values:
        raise KeyError(f"Checkpoint for thread '{thread_id}' is unavailable.")

    resume_payload = {
        "decision": decision,
        "operator_id": operator_id,
        "operator_note": operator_note,
    }
    final_state: dict[str, Any] = graph.invoke(
        Command(resume=resume_payload),
        config=config,
    )

    final_text = str(final_state.get("final_response") or "")
    finalized_trace = trace_recorder.finalize_trace(
        resume_trace.trace_id,
        routed_agents=list(final_state.get("routed_agents") or []),
        tools_used=list(final_state.get("tools_used") or []),
        sources=list(final_state.get("sources") or []),
        confidence_score=float(final_state.get("confidence_score") or 0.48),
        guardrail_triggered=False,
        handoff_required=True,
        final_response=final_text,
        status="escalated",
    )

    handoff_store.mark_resolved(
        thread_id=thread_id,
        decision=decision,
        operator_id=operator_id,
        operator_note=operator_note,
        final_response=finalized_trace.final_response,
    )
    session_store.add_message(
        user_id=user_id, role="assistant", content=finalized_trace.final_response
    )

    return {
        "response": finalized_trace.final_response,
        "user_id": user_id,
        "routed_agents": finalized_trace.routed_agents,
        "tools_used": finalized_trace.tools_used,
        "sources": finalized_trace.sources,
        "confidence_score": finalized_trace.confidence_score,
        "guardrail_triggered": False,
        "handoff_required": True,
        "handoff_status": "resolved",
        "thread_id": thread_id,
        "human_decision": final_state.get("human_decision") or resume_payload,
        "trace_id": finalized_trace.trace_id,
        "latency_ms": finalized_trace.total_latency_ms,
        "effective_slo_target_ms": finalized_trace.effective_slo_target_ms,
        "slo_tier": finalized_trace.slo_tier,
        "slo_violated": finalized_trace.slo_violated,
        "total_tokens": finalized_trace.total_tokens,
        "prompt_tokens": finalized_trace.prompt_tokens,
        "completion_tokens": finalized_trace.completion_tokens,
        "router_plan": final_state.get("router_plan") or {},
        "retrieved_contexts": _extract_retrieved_contexts(
            list(final_state.get("agent_outputs") or [])
        ),
        "chat_history": session_store.get_history(user_id),
    }


async def execute_orchestration_stream(
    message: str,
    user_id: str,
    trace_id: str | None = None,
    thread_id: str | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Stream compiled LangGraph orchestration node updates, token output, and HITL interrupt events."""
    trace = trace_recorder.create_trace(
        user_id=user_id,
        message=message,
        trace_id=trace_id,
    )
    resolved_thread_id = thread_id or f"thr-{trace.trace_id}"

    yield {
        "event": "start",
        "trace_id": trace.trace_id,
        "thread_id": resolved_thread_id,
        "user_id": user_id,
    }

    initial_state: OrchestrationState = {
        "trace_id": trace.trace_id,
        "thread_id": resolved_thread_id,
        "user_id": user_id,
        "message": message,
        "language": "en",
        "guardrail_triggered": False,
        "guardrail_reason": "",
        "router_plan": {},
        "agent_queue": [],
        "routed_agents": [],
        "agent_outputs": [],
        "tools_used": [],
        "sources": [],
        "confidence_score": 1.0,
        "handoff_required": False,
        "handoff_status": "none",
        "human_decision": None,
        "escalation_details": None,
        "final_response": "",
        "chat_history": session_store.get_history(user_id),
        "rewritten_query": message,
    }

    graph = get_orchestration_graph()
    config = {"configurable": {"thread_id": resolved_thread_id}}
    state: dict[str, Any] = dict(initial_state)
    interrupted_payload: dict[str, Any] | None = None

    for chunk in graph.stream(initial_state, config=config, stream_mode="updates"):
        if "__interrupt__" in chunk:
            ints = chunk["__interrupt__"]
            first = ints[0] if ints else {}
            int_val = getattr(first, "value", first)
            interrupted_payload = (
                dict(int_val)
                if isinstance(int_val, dict)
                else {"protocol_id": "ESC-GN-PENDING", "ticket_id": "TCK-2026-ESC"}
            )
            yield {"event": "node_started", "node": "escalation_agent"}
            yield {
                "event": "node_completed",
                "node": "escalation_agent",
                "tools_used": ["dispatch_human_handoff", "manage_support_ticket"],
                "handoff_status": "pending_human_review",
            }
            yield {
                "event": "interrupt",
                "thread_id": resolved_thread_id,
                "handoff_status": "pending_human_review",
                "data": interrupted_payload,
            }
            break

        for node_name, update in chunk.items():
            if not isinstance(update, dict):
                continue
            yield {"event": "node_started", "node": node_name}
            state.update(update)

            if node_name == "input_guardrail":
                yield {
                    "event": "node_completed",
                    "node": "input_guardrail",
                    "blocked": bool(state.get("guardrail_triggered", False)),
                }
            elif node_name == "router_agent":
                plan = state.get("router_plan") or {}
                yield {
                    "event": "node_completed",
                    "node": "router_agent",
                    "routed_agents": list(state.get("agent_queue") or []),
                    "primary_intent": plan.get("primary_intent"),
                }
            elif node_name == "personality_agent":
                final_txt = str(state.get("final_response") or "")
                words = final_txt.split(" ")
                for idx, word in enumerate(words):
                    yield {
                        "event": "token",
                        "token": word if idx == len(words) - 1 else f"{word} ",
                    }
                yield {"event": "node_completed", "node": "personality_agent"}
            else:
                yield {
                    "event": "node_completed",
                    "node": node_name,
                    "tools_used": list(update.get("tools_used") or state.get("tools_used") or []),
                    "confidence": update.get("confidence_score", state.get("confidence_score")),
                }

    if interrupted_payload is not None:
        paused_payload = _build_interrupted_result(
            trace_id=trace.trace_id,
            thread_id=resolved_thread_id,
            user_id=user_id,
            message=message,
            state_snapshot=state,
            interrupt_payload=interrupted_payload,
        )
        yield {"event": "final_result", "data": paused_payload}
        return

    finalized_trace = trace_recorder.finalize_trace(
        trace.trace_id,
        routed_agents=list(state.get("routed_agents") or []),
        tools_used=list(state.get("tools_used") or []),
        sources=list(state.get("sources") or []),
        confidence_score=float(state.get("confidence_score") or 1.0),
        guardrail_triggered=bool(state.get("guardrail_triggered", False)),
        handoff_required=bool(state.get("handoff_required", False)),
        final_response=str(state.get("final_response") or ""),
    )

    session_store.add_message(user_id=user_id, role="user", content=message)
    session_store.add_message(
        user_id=user_id, role="assistant", content=finalized_trace.final_response
    )

    final_payload = {
        "response": finalized_trace.final_response,
        "user_id": user_id,
        "routed_agents": finalized_trace.routed_agents,
        "tools_used": finalized_trace.tools_used,
        "sources": finalized_trace.sources,
        "confidence_score": finalized_trace.confidence_score,
        "guardrail_triggered": finalized_trace.guardrail_triggered,
        "handoff_required": finalized_trace.handoff_required,
        "handoff_status": str(state.get("handoff_status") or "none"),
        "thread_id": resolved_thread_id,
        "human_decision": state.get("human_decision"),
        "trace_id": finalized_trace.trace_id,
        "latency_ms": finalized_trace.total_latency_ms,
        "effective_slo_target_ms": finalized_trace.effective_slo_target_ms,
        "slo_tier": finalized_trace.slo_tier,
        "slo_violated": finalized_trace.slo_violated,
        "total_tokens": finalized_trace.total_tokens,
        "prompt_tokens": finalized_trace.prompt_tokens,
        "completion_tokens": finalized_trace.completion_tokens,
        "router_plan": state.get("router_plan") or {},
        "retrieved_contexts": _extract_retrieved_contexts(
            list(state.get("agent_outputs") or [])
        ),
        "chat_history": session_store.get_history(user_id),
    }

    yield {"event": "final_result", "data": final_payload}
