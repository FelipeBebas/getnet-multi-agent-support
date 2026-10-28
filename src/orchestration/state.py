"""Typed LangGraph state schema and Pydantic routing contracts for multi-agent orchestration."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field

SpecializedAgentName = Literal[
    "knowledge_agent",
    "customer_support_agent",
    "escalation_agent",
]


class RouterPlan(BaseModel):
    """Structured routing decision produced by Agent 1 (Router Agent)."""

    primary_intent: Literal[
        "knowledge", "customer_support", "escalation", "hybrid", "out_of_scope"
    ] = Field(
        description="Classified high-level intent category."
    )
    agent_queue: list[SpecializedAgentName] = Field(
        default_factory=list,
        description="Ordered list of specialized agents to execute sequentially.",
    )
    knowledge_sub_intent: Literal["product_rag", "external_web_search", "both", "none"] = Field(
        default="none",
        description="Sub-intent for the Knowledge Agent (RAG vs. Web Search).",
    )
    support_sub_intent: Literal[
        "settlement", "pos_connectivity", "transaction_decline", "ticket", "all", "none"
    ] = Field(
        default="none",
        description="Sub-intent for the Customer Support Agent tools.",
    )
    confidence: float = Field(
        default=0.95,
        ge=0.0,
        le=1.0,
        description="Router classification confidence score.",
    )
    language: Literal["en", "pt"] = Field(
        default="en",
        description="Detected language of the incoming user message.",
    )
    reasoning: str = Field(
        default="",
        description="Brief explanation for the selected agent routing plan.",
    )
    token_usage: dict[str, int] = Field(
        default_factory=dict,
        description="Optional captured token usage from ChatOpenAI response.",
    )
    rewritten_query: str = Field(
        default="",
        description="Standalone contextual query produced by Contextual Query Rewriter.",
    )


class AgentStepOutput(BaseModel):
    """Structured intermediate output produced by a specialized agent node."""

    agent_name: str
    content: str
    tools_used: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    confidence: float = 0.92
    handoff_required: bool = False
    raw_data: dict[str, Any] = Field(default_factory=dict)
    token_usage: dict[str, int] = Field(default_factory=dict)


class OrchestrationState(TypedDict, total=False):
    """Shared state dictionary propagated across all nodes of the LangGraph workflow."""

    trace_id: str
    user_id: str
    message: str
    language: str
    guardrail_triggered: bool
    guardrail_reason: str
    router_plan: dict[str, Any]
    agent_queue: list[str]
    routed_agents: list[str]
    agent_outputs: list[dict[str, Any]]
    tools_used: list[str]
    sources: list[str]
    confidence_score: float
    handoff_required: bool
    escalation_details: dict[str, Any] | None
    final_response: str
    chat_history: list[dict[str, str]]
    rewritten_query: str
