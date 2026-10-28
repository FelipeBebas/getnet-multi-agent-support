"""Centralized application settings using Pydantic Settings."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Typed environment and runtime settings for the Getnet Multi-Agent Support System."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application & HTTP Server ---
    app_name: str = Field(
        default="Getnet Multi-Agent Support System",
        description="Human-readable service name.",
    )
    app_version: str = Field(default="1.0.0", description="Semantic version of the service.")
    app_env: Literal["development", "staging", "production", "test"] = Field(
        default="development",
        description="Runtime environment identifier.",
    )
    log_level: str = Field(default="INFO", description="Minimum log severity level.")
    host: str = Field(default="0.0.0.0", description="Bind host for Uvicorn HTTP server.")
    port: int = Field(default=8000, description="Bind port for Uvicorn HTTP server.")

    # --- LLM & Embeddings Configuration ---
    llm_provider: Literal["auto", "openai", "mock"] = Field(
        default="auto",
        description="LLM provider strategy: 'openai', 'mock', or 'auto' (uses OpenAI when key is present).",
    )
    openai_api_key: str = Field(default="", description="OpenAI API key for chat and embeddings.")
    openai_model: str = Field(default="gpt-4o-mini", description="Default chat completion model.")
    openai_embedding_model: str = Field(
        default="text-embedding-3-small",
        description="Default OpenAI embedding model for ChromaDB.",
    )
    openai_temperature_router: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        description="Temperature for deterministic Router Agent classification.",
    )
    openai_temperature_agent: float = Field(
        default=0.1,
        ge=0.0,
        le=2.0,
        description="Temperature for Knowledge, Support, and Escalation agents.",
    )
    openai_temperature_personality: float = Field(
        default=0.2,
        ge=0.0,
        le=2.0,
        description="Temperature for the Personality Synthesis Agent.",
    )

    # --- Knowledge Base (RAG) & Data Paths ---
    chroma_persist_dir: str = Field(
        default="data/chroma_db",
        description="Directory path for persistent ChromaDB storage.",
    )
    chroma_collection_name: str = Field(
        default="getnet_knowledge_base",
        description="ChromaDB collection name for Getnet documents.",
    )
    knowledge_base_dir: str = Field(
        default="data/knowledge_base",
        description="Directory containing curated and cached markdown corpus files.",
    )
    merchants_data_path: str = Field(
        default="data/merchants.json",
        description="Path to the merchant mock repository (including cliente1988).",
    )
    eval_dataset_path: str = Field(
        default="data/eval_dataset.json",
        description="Path to the automated evaluation dataset.",
    )
    rag_top_k: int = Field(
        default=4,
        ge=1,
        le=20,
        description="Number of top chunks retrieved from the vector store per query.",
    )
    rag_min_similarity_threshold: float = Field(
        default=0.35,
        ge=0.0,
        le=1.0,
        description="Minimum similarity score before triggering live Getnet domain search fallback.",
    )

    # --- External Web Search ---
    tavily_api_key: str = Field(
        default="",
        description="Optional Tavily API key for web search enrichment.",
    )

    # --- Guardrails, Escalation & SLO Alerting Thresholds ---
    confidence_escalation_threshold: float = Field(
        default=0.60,
        ge=0.0,
        le=1.0,
        description="Confidence score threshold below which requests escalate to a human specialist.",
    )
    latency_slo_threshold_ms: float = Field(
        default=7000.0,
        gt=0.0,
        description="End-to-end request latency threshold (ms) that triggers a HIGH_LATENCY_ALERT.",
    )
    latency_slo_fast_path_ms: float = Field(
        default=7000.0,
        gt=0.0,
        description="Latency SLO target (ms) for Fast Path (local RAG, POS diagnostics, Guardrail blocks, 3 sequential LLMs).",
    )
    latency_slo_complex_path_ms: float = Field(
        default=18000.0,
        gt=0.0,
        description="Latency SLO target (ms) for Deep Research / Corrective RAG / Multi-Agent Handoff path.",
    )
    enable_input_guardrails: bool = Field(
        default=True,
        description="Enable prompt-injection and safety inspection at ingress.",
    )
    enable_output_guardrails: bool = Field(
        default=True,
        description="Enable PCI-DSS PAN and CPF/CNPJ PII masking at egress.",
    )

    # --- Observability: LangSmith ---
    langchain_tracing_v2: bool = Field(
        default=False,
        description="Enable LangSmith native tracing (LANGCHAIN_TRACING_V2).",
    )
    langchain_endpoint: str = Field(
        default="https://api.smith.langchain.com",
        description="LangSmith API endpoint.",
    )
    langchain_api_key: str = Field(
        default="",
        description="LangSmith API key.",
    )
    langchain_project: str = Field(
        default="getnet-multi-agent-support",
        description="LangSmith project name.",
    )

    # --- Observability: Optional Langfuse ---
    langfuse_enabled: bool = Field(
        default=False,
        description="Enable optional Langfuse trace export.",
    )
    langfuse_public_key: str = Field(default="", description="Langfuse public key.")
    langfuse_secret_key: str = Field(default="", description="Langfuse secret key.")
    langfuse_host: str = Field(
        default="https://cloud.langfuse.com",
        description="Langfuse host URL.",
    )

    # --- Local Trace & Alert Persistence ---
    trace_log_path: str = Field(
        default="logs/traces.jsonl",
        description="Local JSONL file path where execution traces are persisted.",
    )
    max_in_memory_traces: int = Field(
        default=500,
        ge=10,
        le=10000,
        description="Maximum number of recent traces retained in the in-memory ring buffer.",
    )

    @property
    def has_openai_key(self) -> bool:
        """Return True when a valid-looking OpenAI API key is configured."""
        cleaned = self.openai_api_key.strip()
        return bool(cleaned) and not cleaned.startswith("your-") and cleaned != "sk-xxx"

    @property
    def use_live_llm(self) -> bool:
        """Determine whether to invoke live OpenAI models or deterministic fallback."""
        if self.llm_provider == "mock":
            return False
        if self.llm_provider == "openai":
            return self.has_openai_key
        return self.has_openai_key

    @property
    def langsmith_enabled(self) -> bool:
        """Return True when LangSmith tracing is enabled and an API key is present."""
        return bool(self.langchain_tracing_v2 and self.langchain_api_key.strip())

    def resolve_path(self, relative_or_abs: str) -> Path:
        """Resolve a configured path relative to the repository root if not absolute."""
        path = Path(relative_or_abs)
        if path.is_absolute():
            return path
        return PROJECT_ROOT / path

    def configure_langsmith_env(self) -> None:
        """Synchronize LangSmith settings with os.environ for LangChain/LangGraph."""
        if self.langsmith_enabled:
            os.environ["LANGCHAIN_TRACING_V2"] = "true"
            os.environ["LANGCHAIN_ENDPOINT"] = self.langchain_endpoint
            os.environ["LANGCHAIN_API_KEY"] = self.langchain_api_key
            os.environ["LANGCHAIN_PROJECT"] = self.langchain_project
        else:
            os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached singleton Settings instance."""
    cfg = Settings()
    cfg.configure_langsmith_env()
    return cfg


settings = get_settings()
