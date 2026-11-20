"""Sliding-window rate limiter and per-user LLM token budget enforcement (anti-token maxxing)."""

from __future__ import annotations

import math
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from fastapi import HTTPException, status

from src.config.settings import settings
from src.observability.logger import get_logger
from src.observability.tracer import trace_recorder

logger = get_logger("api.rate_limit")


class SlidingWindowRateLimiter:
    """Thread-safe in-memory sliding-window HTTP rate limiter."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check_and_consume(
        self,
        key: str,
        max_requests: int | None = None,
        window_seconds: int | None = None,
    ) -> dict[str, int]:
        """Record a request hit for key or raise HTTP 429 with Retry-After when exceeded."""
        limit = int(max_requests or settings.rate_limit_requests_per_minute)
        window = int(window_seconds or settings.rate_limit_window_seconds)
        now = time.monotonic()
        cutoff = now - window

        with self._lock:
            bucket = self._hits[key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()

            if len(bucket) >= limit:
                oldest = bucket[0]
                retry_after = max(1, int(math.ceil(window - (now - oldest))))
                logger.warning(
                    "api_rate_limit_exceeded",
                    caller_key=key,
                    limit=limit,
                    window_seconds=window,
                    retry_after=retry_after,
                )
                trace_recorder.record_operational_alert(
                    user_id=key,
                    alert_type="RATE_LIMIT_ALERT",
                    message=f"Rate limit exceeded ({limit} requests per {window}s).",
                    details={"limit": limit, "window_seconds": window, "retry_after": retry_after},
                )
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded ({limit} requests per {window}s). Retry later.",
                    headers={"Retry-After": str(retry_after)},
                )

            bucket.append(now)
            remaining = max(0, limit - len(bucket))
            return {"limit": limit, "remaining": remaining, "window_seconds": window}

    def reset(self) -> None:
        """Clear all recorded rate-limit windows (intended for tests)."""
        with self._lock:
            self._hits.clear()


class TokenBudgetTracker:
    """Thread-safe daily LLM token budget tracker per user_id."""

    def __init__(self) -> None:
        self._usage: dict[tuple[str, str], int] = defaultdict(int)
        self._lock = threading.Lock()

    @staticmethod
    def _today_key() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def check_budget(self, user_id: str, daily_limit: int | None = None) -> dict[str, int]:
        """Verify user_id has remaining daily token budget or raise HTTP 429."""
        limit = int(daily_limit or settings.daily_token_budget_per_user)
        day = self._today_key()
        with self._lock:
            used = self._usage.get((day, user_id), 0)

        if used >= limit:
            logger.warning(
                "token_budget_exceeded",
                user_id=user_id,
                tokens_used=used,
                daily_limit=limit,
            )
            trace_recorder.record_operational_alert(
                user_id=user_id,
                alert_type="TOKEN_BUDGET_ALERT",
                message=f"Daily token budget exceeded ({used}/{limit} tokens).",
                details={"tokens_used": used, "daily_limit": limit},
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Daily token budget exceeded for user '{user_id}' "
                    f"({used}/{limit} tokens used)."
                ),
                headers={"Retry-After": "3600"},
            )

        return {"used": used, "limit": limit, "remaining": max(0, limit - used)}

    def record_usage(self, user_id: str, total_tokens: int) -> int:
        """Accumulate consumed tokens for user_id on the current UTC date."""
        tokens = max(0, int(total_tokens))
        if tokens == 0:
            return self.get_usage(user_id)["used"]
        day = self._today_key()
        with self._lock:
            self._usage[(day, user_id)] += tokens
            total = self._usage[(day, user_id)]

        if tokens > settings.max_tokens_per_request:
            logger.warning(
                "single_request_token_cap_exceeded",
                user_id=user_id,
                request_tokens=tokens,
                max_tokens_per_request=settings.max_tokens_per_request,
            )
        return total

    def get_usage(self, user_id: str) -> dict[str, int]:
        """Return current daily token usage summary for user_id."""
        day = self._today_key()
        limit = int(settings.daily_token_budget_per_user)
        with self._lock:
            used = self._usage.get((day, user_id), 0)
        return {"used": used, "limit": limit, "remaining": max(0, limit - used)}

    def reset(self) -> None:
        """Clear all tracked token budgets (intended for tests)."""
        with self._lock:
            self._usage.clear()


rate_limiter = SlidingWindowRateLimiter()
token_budget_tracker = TokenBudgetTracker()
