"""Shared pytest fixtures for unit and integration tests."""

from __future__ import annotations

import os
import socket

import pytest

# Prevent pytest-langsmith background threads from crashing on closed stdout in restricted sandboxes
os.environ["LANGCHAIN_TRACING_V2"] = "false"

from fastapi.testclient import TestClient

from src.api.auth import RoleType, create_access_token
from src.api.rate_limit import rate_limiter, token_budget_tracker
from src.config.settings import settings
from src.main import app


def _can_open_outbound_https() -> bool:
    """Return False if the current test runner OS sandbox blocks outbound sockets (WinError 10013)."""
    try:
        with socket.create_connection(("api.openai.com", 443), timeout=1.0):
            return True
    except OSError:
        return False


if not _can_open_outbound_https():
    settings.llm_provider = "mock"
    settings.langchain_tracing_v2 = False

# Isolate test runtime/checkpoint SQLite stores in memory by default
settings.runtime_db_path = ":memory:"
settings.hitl_checkpoint_db_path = ":memory:"


@pytest.fixture(autouse=True)
def _reset_rate_and_budget_state() -> None:
    """Ensure rate limiter and token budget counters start clean for every test."""
    rate_limiter.reset()
    token_budget_tracker.reset()
    yield
    rate_limiter.reset()
    token_budget_tracker.reset()


def make_auth_headers(user_id: str, role: RoleType = "merchant") -> dict[str, str]:
    """Generate Authorization Bearer headers for test calls."""
    token = create_access_token(user_id=user_id, role=role)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def merchant_headers() -> dict[str, str]:
    """Bearer headers scoped to merchant 'cliente1988'."""
    return make_auth_headers("cliente1988", role="merchant")


@pytest.fixture()
def operator_headers() -> dict[str, str]:
    """Bearer headers scoped to an authorized operator."""
    return make_auth_headers("operator_qa", role="operator")


@pytest.fixture()
def api_client() -> TestClient:
    """Return a FastAPI TestClient instance with lifespan initialized."""
    with TestClient(app) as client:
        yield client
