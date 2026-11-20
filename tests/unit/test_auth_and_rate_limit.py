"""Unit tests for JWT authentication, RBAC, tenant isolation, rate limiting, and token budget."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from src.api.auth import (
    Principal,
    assert_user_access,
    create_access_token,
    decode_access_token,
    require_roles,
)
from src.api.rate_limit import SlidingWindowRateLimiter, TokenBudgetTracker
from src.api.schemas import ChatRequest
from src.config.settings import settings


def test_jwt_create_and_decode_valid_tokens() -> None:
    """Verify issued merchant and operator JWTs decode into typed Principal objects."""
    tok = create_access_token("cliente1988", role="merchant", expires_in_seconds=120)
    principal = decode_access_token(tok)
    assert principal.user_id == "cliente1988"
    assert principal.role == "merchant"
    assert len(principal.token_id) > 0


def test_jwt_rejects_invalid_and_expired_tokens() -> None:
    """Verify tampered or expired JWTs raise HTTP 401."""
    with pytest.raises(HTTPException) as exc_invalid:
        decode_access_token("not.a.valid.jwt")
    assert exc_invalid.value.status_code == 401

    expired_tok = create_access_token("cliente1988", role="merchant", expires_in_seconds=-10)
    with pytest.raises(HTTPException) as exc_exp:
        decode_access_token(expired_tok)
    assert exc_exp.value.status_code == 401


def test_rbac_and_tenant_isolation_helpers() -> None:
    """Verify role guard and multi-tenant user_id isolation enforce HTTP 403."""
    merchant = Principal(user_id="cliente1988", role="merchant")
    operator = Principal(user_id="op1", role="operator")

    guard = require_roles("operator", "admin")
    assert guard(operator).role == "operator"
    with pytest.raises(HTTPException) as exc_role:
        guard(merchant)
    assert exc_role.value.status_code == 403

    assert_user_access(merchant, "cliente1988")
    assert_user_access(operator, "cliente1988")
    with pytest.raises(HTTPException) as exc_idor:
        assert_user_access(merchant, "other_merchant")
    assert exc_idor.value.status_code == 403


def test_chat_request_rejects_oversized_message() -> None:
    """Verify ChatRequest enforces settings.max_message_length with ValidationError."""
    too_long = "a" * (settings.max_message_length + 1)
    with pytest.raises(ValidationError, match="maximum allowed length"):
        ChatRequest(message=too_long, user_id="cliente1988")


def test_sliding_window_rate_limiter_throttles_with_429() -> None:
    """Verify SlidingWindowRateLimiter blocks excess requests with 429 and Retry-After."""
    limiter = SlidingWindowRateLimiter()
    limiter.check_and_consume("merchant:u1", max_requests=2, window_seconds=30)
    limiter.check_and_consume("merchant:u1", max_requests=2, window_seconds=30)

    with pytest.raises(HTTPException) as exc:
        limiter.check_and_consume("merchant:u1", max_requests=2, window_seconds=30)
    assert exc.value.status_code == 429
    assert int(exc.value.headers["Retry-After"]) >= 1


def test_token_budget_tracker_enforces_daily_cap() -> None:
    """Verify TokenBudgetTracker tracks usage and blocks exhausted users with HTTP 429."""
    tracker = TokenBudgetTracker()
    tracker.record_usage("u_budget", 400)
    status_info = tracker.check_budget("u_budget", daily_limit=500)
    assert status_info["remaining"] == 100

    tracker.record_usage("u_budget", 150)
    with pytest.raises(HTTPException) as exc:
        tracker.check_budget("u_budget", daily_limit=500)
    assert exc.value.status_code == 429
