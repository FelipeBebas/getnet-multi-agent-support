"""Thread-safe In-Memory Session Store for multi-turn conversational agent orchestration."""

from __future__ import annotations

import threading
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


class SessionMessage(BaseModel):
    """Single turn message stored in conversational session history."""

    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class SessionStore:
    """In-memory multi-turn conversational history store keyed by user_id."""

    def __init__(self, max_history_turns: int = 10) -> None:
        self.max_history_turns = max_history_turns
        self._store: dict[str, list[dict[str, str]]] = defaultdict(list)
        self._lock = threading.Lock()

    def get_history(self, user_id: str) -> list[dict[str, str]]:
        """Return chronological message history list for a user."""
        with self._lock:
            return list(self._store.get(user_id, []))

    def add_message(
        self,
        user_id: str,
        role: Literal["user", "assistant", "system"],
        content: str,
    ) -> None:
        """Append a message turn to the user's session history with ring-buffer pruning."""
        with self._lock:
            history = self._store[user_id]
            history.append(
                {
                    "role": role,
                    "content": content,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
            # Retain up to 2 * max_history_turns (user + assistant pairs)
            max_messages = self.max_history_turns * 2
            if len(history) > max_messages:
                self._store[user_id] = history[-max_messages:]

    def format_history_for_prompt(
        self,
        user_id: str,
        max_turns: int = 5,
    ) -> str:
        """Render recent session turns into a clean dialogue snippet for LLM prompts."""
        history = self.get_history(user_id)
        if not history:
            return ""

        # Take last 2 * max_turns messages
        recent = history[-(max_turns * 2):]
        lines: list[str] = []
        for msg in recent:
            role_label = "User" if msg.get("role") == "user" else "Assistant"
            text = (msg.get("content") or "").strip()
            if text:
                lines.append(f"{role_label}: {text}")

        return "\n".join(lines)

    def clear(self, user_id: str | None = None) -> None:
        """Clear session history for a specific user or wipe all sessions."""
        with self._lock:
            if user_id:
                self._store.pop(user_id, None)
            else:
                self._store.clear()


session_store = SessionStore()
