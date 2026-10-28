"""Pydantic request and response contracts for the FastAPI HTTP service."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    """Expected JSON payload for POST /chat (and POST / alias)."""

    message: str = Field(
        ...,
        min_length=1,
        description="Incoming user query or statement.",
        examples=["What's the difference between the Get Clássica and the Get Smart?"],
    )
    user_id: str = Field(
        ...,
        min_length=1,
        description="Unique merchant/user identifier.",
        examples=["cliente1988"],
    )

    @field_validator("message", "user_id")
    @classmethod
    def _reject_blank_strings(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Field cannot be empty or whitespace only.")
        return cleaned


class ChatResponse(BaseModel):
    """Structured JSON response returned by the multi-agent orchestration."""

    response: str = Field(description="Synthesized final answer in Getnet's support voice.")
    user_id: str = Field(description="Echoed merchant/user identifier.")
    routed_agents: list[str] = Field(
        default_factory=list,
        description="Ordered sequence of agents that processed the request.",
    )
    tools_used: list[str] = Field(
        default_factory=list,
        description="Names of domain/RAG/web tools invoked during execution.",
    )
    sources: list[str] = Field(
        default_factory=list,
        description="Official URLs or internal data sources used to ground the answer.",
    )
    confidence_score: float = Field(
        default=1.0,
        description="End-to-end resolution confidence score in [0.0, 1.0].",
    )
    guardrail_triggered: bool = Field(
        default=False,
        description="True when an input safety/prompt-injection guardrail intercepted the request.",
    )
    handoff_required: bool = Field(
        default=False,
        description="True when the request was escalated to a human specialist queue.",
    )
    trace_id: str = Field(description="Unique execution trace identifier for observability.")
    latency_ms: float = Field(default=0.0, description="Total execution latency in milliseconds.")
    effective_slo_target_ms: float = Field(
        default=4000.0,
        description="Dynamic SLO latency threshold target (ms) based on route complexity.",
    )
    slo_tier: str = Field(
        default="fast_path",
        description="SLO classification tier ('fast_path' or 'complex_path').",
    )
    slo_violated: bool = Field(
        default=False,
        description="True if the request latency exceeded its effective SLO threshold.",
    )
    total_tokens: int = Field(default=0, description="Total LLM tokens consumed across all agent spans.")
    prompt_tokens: int = Field(default=0, description="Total LLM prompt tokens consumed.")
    completion_tokens: int = Field(default=0, description="Total LLM completion tokens generated.")
    router_plan: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured classification output from Agent 1 (Router Agent).",
    )
    chat_history: list[dict[str, str]] = Field(
        default_factory=list,
        description="Recent conversation turns in active session.",
    )


class EvalRunRequest(BaseModel):
    """Payload for POST /evals/run."""

    sync_langsmith: bool = Field(
        default=False,
        description="Whether to sync dataset and execute LangSmith evaluation experiment.",
    )
    max_scenarios: int | None = Field(
        default=None,
        ge=1,
        le=50,
        description="Optional limit on number of scenarios to evaluate.",
    )


class HealthResponse(BaseModel):
    """Service readiness and vector store health status."""

    status: str = "ok"
    app_name: str
    version: str
    vector_store_ready: bool
    vector_store_chunks: int
    llm_mode: str
    langsmith_enabled: bool
    model: str = "gpt-4o-mini"
