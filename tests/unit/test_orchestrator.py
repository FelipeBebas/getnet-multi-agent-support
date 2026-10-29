"""Unit tests for LangGraph orchestrator dispatching and risk-gated conditional escalation."""

from __future__ import annotations

import pytest

from src.orchestration.graph import _dispatch_next_from_queue, execute_orchestration
from src.orchestration.state import AgentStepOutput


def test_dispatch_next_from_queue_suppresses_escalation_for_low_risk_low_confidence() -> None:
    """Verify that low confidence on low-risk queries completes to personality_agent without escalation."""
    state = {
        "router_plan": {"primary_intent": "knowledge", "risk_tier": "low"},
        "agent_queue": [],
        "confidence_score": 0.45,
        "routed_agents": ["router_agent", "knowledge_agent"],
    }
    next_node = _dispatch_next_from_queue(state)  # type: ignore[arg-type]
    assert next_node == "personality_agent"


@pytest.mark.parametrize("risk_tier", ["high", "medium"])
def test_dispatch_next_from_queue_triggers_escalation_for_high_and_medium_risk(
    risk_tier: str,
) -> None:
    """Verify that low confidence on high or medium risk queries routes to escalation_agent."""
    state = {
        "router_plan": {"primary_intent": "customer_support", "risk_tier": risk_tier},
        "agent_queue": [],
        "confidence_score": 0.45,
        "routed_agents": ["router_agent", "knowledge_agent"],
    }
    next_node = _dispatch_next_from_queue(state)  # type: ignore[arg-type]
    assert next_node == "escalation_agent"


def test_e2e_low_risk_informational_query_with_low_confidence_does_not_escalate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify end-to-end execution of a low-risk informational query with low confidence does NOT trigger escalation."""
    import src.orchestration.graph as graph_module

    def _mock_run_knowledge_low_conf(message: str, sub_intent: str, chat_history: list | None = None) -> AgentStepOutput:
        return AgentStepOutput(
            agent_name="knowledge_agent",
            content="Registros oficiais não trazem essa informação histórica. [INSUFFICIENT_EVIDENCE]",
            tools_used=["retrieve_getnet_knowledge"],
            sources=[],
            confidence=0.45,
            handoff_required=False,
        )

    monkeypatch.setattr(graph_module, "run_knowledge_agent", _mock_run_knowledge_low_conf)

    out = execute_orchestration(
        message="Quando foi lançado o satélite holográfico fictício?",
        user_id="cliente1988",
    )

    # Low confidence detected from epistemic uncertainty
    assert out["confidence_score"] < 0.60
    # Business risk is low -> escalation suppressed
    assert out["handoff_required"] is False
    assert "escalation_agent" not in out["routed_agents"]
    assert "personality_agent" in out["routed_agents"]


def test_e2e_high_risk_dispute_query_with_low_confidence_triggers_escalation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify end-to-end execution of a high/medium risk query with low confidence DOES trigger escalation."""
    import src.orchestration.graph as graph_module

    def _mock_run_knowledge_low_conf(message: str, sub_intent: str, chat_history: list | None = None) -> AgentStepOutput:
        return AgentStepOutput(
            agent_name="knowledge_agent",
            content="Não foi possível verificar a contestação de estorno na base. [INSUFFICIENT_EVIDENCE]",
            tools_used=["retrieve_getnet_knowledge"],
            sources=[],
            confidence=0.45,
            handoff_required=False,
        )

    monkeypatch.setattr(graph_module, "run_knowledge_agent", _mock_run_knowledge_low_conf)

    out = execute_orchestration(
        message="Contestação de estorno de valor não localizado na conta",
        user_id="cliente1988",
    )

    # Low confidence triggers escalation for high-risk dispute
    assert out["confidence_score"] < 0.60
    assert out["handoff_required"] is True
    assert "escalation_agent" in out["routed_agents"]
