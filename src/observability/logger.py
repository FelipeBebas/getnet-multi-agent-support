"""Structured JSON logging configuration using structlog."""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from src.config.settings import settings

_LOGGING_CONFIGURED = False


def configure_logging(log_level: str | None = None) -> None:
    """Configure standard library logging and structlog for JSON output."""
    global _LOGGING_CONFIGURED
    effective_level_name = (log_level or settings.log_level or "INFO").upper()
    numeric_level = getattr(logging, effective_level_name, logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=numeric_level,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=False,
    )
    _LOGGING_CONFIGURED = True


def get_logger(name: str = "getnet", **initial_values: Any) -> Any:
    """Return a structured logger bound with optional initial context fields."""
    if not _LOGGING_CONFIGURED:
        configure_logging()
    return structlog.get_logger(logger_name=name, **initial_values)


def bind_trace_context(
    trace_id: str,
    user_id: str | None = None,
    **extra: Any,
) -> None:
    """Bind request-scoped trace identifiers into structlog contextvars."""
    ctx: dict[str, Any] = {"trace_id": trace_id}
    if user_id is not None:
        ctx["user_id"] = user_id
    ctx.update(extra)
    structlog.contextvars.bind_contextvars(**ctx)


def clear_trace_context() -> None:
    """Clear request-scoped structlog contextvars."""
    structlog.contextvars.clear_contextvars()
