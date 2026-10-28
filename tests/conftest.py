"""Shared pytest fixtures for unit and integration tests."""

from __future__ import annotations

import os
import socket

import pytest

# Prevent pytest-langsmith background threads from crashing on closed stdout in restricted sandboxes
os.environ["LANGCHAIN_TRACING_V2"] = "false"

from fastapi.testclient import TestClient

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


@pytest.fixture()
def api_client() -> TestClient:
    """Return a FastAPI TestClient instance with lifespan initialized."""
    with TestClient(app) as client:
        yield client
