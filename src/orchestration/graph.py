"""LangGraph StateGraph builder and execution runner for the 5-agent Getnet orchestration."""

from __future__ import annotations

from typing import Any, AsyncGenerator

from langgraph.graph import END, START, StateGraph

from src.agents.escalation_agent import run_escalation_agent
from src.agents.knowledge_agent import run_knowledge_agent
from src.agents.personality_agent import run_personality_agent, stream_personality_agent
from src.agents.router_agent import classify_and_route
from src.agents.support_agent import run_customer_support_agent
from src.config.settings import settings
from src.guardrails.validator import (
    sanitize_output_message,
    validate_input_message,
)
from src.observability.logger import get_logger
from src.observability.tracer import trace_recorder, traceable_step
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
    message = state["message"]
    user_id = state["user_id"]
    current_conf = float(state.get("confidence_score") or 0.48)

    queue = [a for a in (state.get("agent_queue") or []) if a != "escalation_agent"]

    reason = (
        "Epistemic uncertainty: unverified out-of-corpus knowledge or low confidence threshold (< 0.60)"
        if current_conf < settings.confidence_escalation_threshold
        else "Explicit human specialist request or complex policy escalation"
    )

    with trace_recorder.record_span(
        trace_id=trace_id,
        name="escalation_agent_execute",
        agent="escalation_agent",
        span_type="agent",
        inputs={"message": message, "user_id": user_id, "reason": reason},
    ) as span:
        step_out = run_escalation_agent(
            message=message,
            user_id=user_id,
            reason=reason,
            confidence_score=min(current_conf, 0.48),
        )
        span.set_output(
            tools_used=step_out.tools_used,
            handoff_required=True,
        )

    for tool_name in step_out.tools_used:
        with trace_recorder.record_span(
            trace_id=trace_id,
            name=tool_name,
            agent="escalation_agent",
            span_type="tool",
            inputs={"user_id": user_id},
        ) as t_span:
            t_span.set_output(handoff_required=True)

    routed = list(state.get("routed_agents") or [])
    routed.append("escalation_agent")

    outputs = list(state.get("agent_outputs") or [])
    outputs.append(step_out.model_dump())

    tools = list(state.get("tools_used") or [])
    tools.extend(step_out.tools_used)

    sources = list(state.get("sources") or [])
    sources.extend(step_out.sources)

    return {
        "agent_queue": queue,
        "routed_agents": routed,
        "agent_outputs": outputs,
        "tools_used": list(dict.fromkeys(tools)),
        "sources": list(dict.fromkeys(sources)),
        "confidence_score": step_out.confidence,
        "handoff_required": True,
        "escalation_details": step_out.raw_data,
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


def build_orchestration_graph() -> Any:
    """Construct and compile the 5-agent LangGraph StateGraph workflow."""
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

    return workflow.compile()


_compiled_graph: Any = None


def get_orchestration_graph() -> Any:
    """Return cached compiled LangGraph instance."""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_orchestration_graph()
    return _compiled_graph


@traceable_step(name="getnet_multi_agent_orchestration", run_type="chain")
def execute_orchestration(
    message: str,
    user_id: str,
    trace_id: str | None = None,
) -> dict[str, Any]:
    """Run an incoming user request end-to-end through the LangGraph orchestration and record trace."""
    trace = trace_recorder.create_trace(
        user_id=user_id,
        message=message,
        trace_id=trace_id,
    )

    initial_state: OrchestrationState = {
        "trace_id": trace.trace_id,
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
        "escalation_details": None,
        "final_response": "",
        "chat_history": session_store.get_history(user_id),
        "rewritten_query": message,
    }

    graph = get_orchestration_graph()
    final_state: OrchestrationState = graph.invoke(initial_state)

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

    # Persist completed turn to session memory store
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
        "trace_id": finalized_trace.trace_id,
        "latency_ms": finalized_trace.total_latency_ms,
        "effective_slo_target_ms": finalized_trace.effective_slo_target_ms,
        "slo_tier": finalized_trace.slo_tier,
        "slo_violated": finalized_trace.slo_violated,
        "total_tokens": finalized_trace.total_tokens,
        "prompt_tokens": finalized_trace.prompt_tokens,
        "completion_tokens": finalized_trace.completion_tokens,
        "router_plan": final_state.get("router_plan") or {},
        "chat_history": session_store.get_history(user_id),
    }


async def execute_orchestration_stream(
    message: str,
    user_id: str,
    trace_id: str | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Execute the multi-agent graph, streaming node lifecycle events and real-time tokens."""
    trace = trace_recorder.create_trace(
        user_id=user_id,
        message=message,
        trace_id=trace_id,
    )

    yield {
        "event": "start",
        "trace_id": trace.trace_id,
        "user_id": user_id,
    }

    state: OrchestrationState = {
        "trace_id": trace.trace_id,
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
        "escalation_details": None,
        "final_response": "",
        "chat_history": session_store.get_history(user_id),
        "rewritten_query": message,
    }

    # Step 1: Input Guardrail
    yield {"event": "node_started", "node": "input_guardrail"}
    in_update = _input_guardrail_node(state)
    state.update(in_update)
    is_blocked = bool(state.get("guardrail_triggered", False))
    yield {
        "event": "node_completed",
        "node": "input_guardrail",
        "blocked": is_blocked,
    }

    if is_blocked:
        yield {"event": "node_started", "node": "output_guardrail"}
        out_update = _output_guardrail_node(state)
        state.update(out_update)
        yield {"event": "node_completed", "node": "output_guardrail"}
    else:
        # Step 2: Router Agent
        yield {"event": "node_started", "node": "router_agent"}
        router_update = _router_agent_node(state)
        state.update(router_update)
        plan = state.get("router_plan") or {}
        yield {
            "event": "node_completed",
            "node": "router_agent",
            "routed_agents": list(state.get("agent_queue") or []),
            "primary_intent": plan.get("primary_intent"),
        }

        # Step 3: Domain Specialists Loop
        while True:
            next_step = _dispatch_next_from_queue(state)
            if next_step == "personality_agent":
                break
            elif next_step == "knowledge_agent":
                yield {"event": "node_started", "node": "knowledge_agent"}
                k_update = _knowledge_agent_node(state)
                state.update(k_update)
                yield {
                    "event": "node_completed",
                    "node": "knowledge_agent",
                    "tools_used": list(k_update.get("tools_used") or []),
                    "confidence": k_update.get("confidence_score"),
                }
            elif next_step == "customer_support_agent":
                yield {"event": "node_started", "node": "customer_support_agent"}
                s_update = _customer_support_agent_node(state)
                state.update(s_update)
                yield {
                    "event": "node_completed",
                    "node": "customer_support_agent",
                    "tools_used": list(s_update.get("tools_used") or []),
                    "confidence": s_update.get("confidence_score"),
                }
            elif next_step == "escalation_agent":
                yield {"event": "node_started", "node": "escalation_agent"}
                e_update = _escalation_agent_node(state)
                state.update(e_update)
                yield {
                    "event": "node_completed",
                    "node": "escalation_agent",
                    "tools_used": list(e_update.get("tools_used") or []),
                    "confidence": e_update.get("confidence_score"),
                }
            else:
                break

        # Step 4: Personality Agent (Token Streaming)
        yield {"event": "node_started", "node": "personality_agent"}
        routed = list(state.get("routed_agents") or [])
        routed.append("personality_agent")
        state["routed_agents"] = routed

        full_response_parts: list[str] = []
        for token_chunk in stream_personality_agent(
            message=state.get("rewritten_query") or state["message"],
            user_id=state["user_id"],
            agent_outputs=list(state.get("agent_outputs") or []),
            language=str(state.get("language") or "en"),
            handoff_required=bool(state.get("handoff_required", False)),
            chat_history=state.get("chat_history") or [],
        ):
            full_response_parts.append(token_chunk)
            yield {"event": "token", "token": token_chunk}

        synthesized_text = "".join(full_response_parts).strip()
        state["final_response"] = synthesized_text
        yield {"event": "node_completed", "node": "personality_agent"}

        # Step 5: Output Guardrail
        yield {"event": "node_started", "node": "output_guardrail"}
        out_update = _output_guardrail_node(state)
        state.update(out_update)
        yield {"event": "node_completed", "node": "output_guardrail"}

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
        "trace_id": finalized_trace.trace_id,
        "latency_ms": finalized_trace.total_latency_ms,
        "effective_slo_target_ms": finalized_trace.effective_slo_target_ms,
        "slo_tier": finalized_trace.slo_tier,
        "slo_violated": finalized_trace.slo_violated,
        "total_tokens": finalized_trace.total_tokens,
        "prompt_tokens": finalized_trace.prompt_tokens,
        "completion_tokens": finalized_trace.completion_tokens,
        "router_plan": state.get("router_plan") or {},
        "chat_history": session_store.get_history(user_id),
    }

    yield {"event": "final_result", "data": final_payload}
