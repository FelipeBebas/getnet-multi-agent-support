"""SQLite-backed Thread-safe Session Store for multi-turn conversational agent orchestration."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from src.orchestration.persistence import open_sqlite_connection, resolve_sqlite_target


class SessionMessage(BaseModel):
    """Single turn message stored in conversational session history."""

    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class SessionStore:
    """Persistent SQLite-backed multi-turn conversational history store keyed by user_id."""

    def __init__(
        self,
        max_history_turns: int = 10,
        db_path: str | Path | None = None,
    ) -> None:
        self.max_history_turns = max_history_turns
        self._explicit_db_path = db_path
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._active_target: str | None = None

    def _get_conn(self) -> sqlite3.Connection:
        target = resolve_sqlite_target(self._explicit_db_path)
        if self._conn is None or self._active_target != target:
            if self._conn is not None:
                self._conn.close()
            self._conn = open_sqlite_connection(target)
            self._active_target = target
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS session_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_session_user_id ON session_messages(user_id, id)"
            )
            self._conn.commit()
        return self._conn

    def get_history(self, user_id: str) -> list[dict[str, str]]:
        """Return chronological message history list for a user."""
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT role, content, timestamp FROM session_messages WHERE user_id = ? ORDER BY id ASC",
                (user_id,),
            ).fetchall()
            return [
                {"role": r["role"], "content": r["content"], "timestamp": r["timestamp"]}
                for r in rows
            ]

    def add_message(
        self,
        user_id: str,
        role: Literal["user", "assistant", "system"],
        content: str,
    ) -> None:
        """Append a message turn to the user's session history with ring-buffer pruning."""
        ts = datetime.now(timezone.utc).isoformat()
        max_messages = self.max_history_turns * 2
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "INSERT INTO session_messages (user_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                (user_id, role, content, ts),
            )
            conn.execute(
                """
                DELETE FROM session_messages
                WHERE user_id = ?
                  AND id NOT IN (
                    SELECT id FROM session_messages
                    WHERE user_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                  )
                """,
                (user_id, user_id, max_messages),
            )
            conn.commit()

    def format_history_for_prompt(
        self,
        user_id: str,
        max_turns: int = 5,
    ) -> str:
        """Render recent session turns into a clean dialogue snippet for LLM prompts."""
        history = self.get_history(user_id)
        if not history:
            return ""

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
            conn = self._get_conn()
            if user_id:
                conn.execute("DELETE FROM session_messages WHERE user_id = ?", (user_id,))
            else:
                conn.execute("DELETE FROM session_messages")
            conn.commit()


session_store = SessionStore()
