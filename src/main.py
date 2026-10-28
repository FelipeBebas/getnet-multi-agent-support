"""FastAPI application entrypoint for the Getnet Multi-Agent Support System."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from src.api.routes import router
from src.config.settings import settings
from src.observability.logger import configure_logging, get_logger
from src.rag.vector_store import get_vector_store

logger = get_logger("main")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Initialize structured logging and seed the ChromaDB knowledge base on startup."""
    configure_logging(settings.log_level)
    settings.configure_langsmith_env()
    store = get_vector_store()
    chunks_count = store.ensure_initialized(include_live_scrape=False)
    logger.info(
        "application_startup_complete",
        app_name=settings.app_name,
        version=settings.app_version,
        vector_store_chunks=chunks_count,
        llm_provider=settings.llm_provider,
        langsmith_enabled=settings.langsmith_enabled,
    )
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Spec-Driven Multi-Agent Support System for Getnet combining LangGraph orchestration, "
        "3-Layer RAG (ChromaDB + Live Domain Fallback), Web Search, Customer Support Tools, "
        "Input/Output Guardrails, Human Escalation, and LangSmith/Local Observability."
    ),
    lifespan=lifespan,
)

app.include_router(router)


if __name__ == "__main__":  # pragma: no cover
    uvicorn.run(
        "src.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )
