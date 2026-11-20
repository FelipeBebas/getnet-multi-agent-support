"""Shared SQLite persistence helpers for session memory, support tickets, and HITL handoffs."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config.settings import settings


def resolve_sqlite_target(explicit_path: str | Path | None = None) -> str:
    """Resolve an explicit or configured SQLite path, preserving ':memory:'."""
    raw = str(explicit_path if explicit_path is not None else settings.runtime_db_path).strip()
    if not raw or raw == ":memory:":
        return ":memory:"
    resolved = settings.resolve_path(raw)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return str(resolved)


def open_sqlite_connection(target: str) -> sqlite3.Connection:
    """Open a thread-safe SQLite connection with WAL mode enabled for file databases."""
    conn = sqlite3.connect(target, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    if target != ":memory:":
        conn.execute("PRAGMA journal_mode=WAL;")
    return conn


class HandoffStore:
    """Persistent SQLite repository tracking LangGraph HITL handoff threads and decisions."""

    def __init__(self, db_path: str | Path | None = None) -> None:
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
                CREATE TABLE IF NOT EXISTS hitl_handoffs (
                    thread_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    protocol_id TEXT NOT NULL,
                    ticket_id TEXT NOT NULL,
                    risk_tier TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    message_preview TEXT NOT NULL,
                    status TEXT NOT NULL,
                    decision TEXT,
                    operator_id TEXT,
                    operator_note TEXT,
                    final_response TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._conn.commit()
        return self._conn

    def upsert_pending(
        self,
        *,
        thread_id: str,
        trace_id: str,
        user_id: str,
        protocol_id: str,
        ticket_id: str,
        risk_tier: str,
        reason: str,
        message_preview: str,
    ) -> dict[str, Any]:
        """Insert or update a pending HITL handoff record."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                """
                INSERT INTO hitl_handoffs (
                    thread_id, trace_id, user_id, protocol_id, ticket_id,
                    risk_tier, reason, message_preview, status,
                    decision, operator_id, operator_note, final_response,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending_human_review', NULL, NULL, NULL, NULL, ?, ?)
                ON CONFLICT(thread_id) DO UPDATE SET
                    trace_id=excluded.trace_id,
                    reason=excluded.reason,
                    status='pending_human_review',
                    updated_at=excluded.updated_at
                """,
                (
                    thread_id,
                    trace_id,
                    user_id,
                    protocol_id,
                    ticket_id,
                    risk_tier,
                    reason,
                    message_preview[:200],
                    now,
                    now,
                ),
            )
            conn.commit()
        return self.get(thread_id) or {}

    def mark_resolved(
        self,
        *,
        thread_id: str,
        decision: str,
        operator_id: str,
        operator_note: str,
        final_response: str,
    ) -> dict[str, Any] | None:
        """Mark a pending HITL handoff as resolved with specialist decision metadata."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                """
                UPDATE hitl_handoffs
                SET status = 'resolved',
                    decision = ?,
                    operator_id = ?,
                    operator_note = ?,
                    final_response = ?,
                    updated_at = ?
                WHERE thread_id = ?
                """,
                (decision, operator_id, operator_note, final_response, now, thread_id),
            )
            conn.commit()
        return self.get(thread_id)

    def get(self, thread_id: str) -> dict[str, Any] | None:
        """Fetch a single HITL handoff record by thread_id."""
        with self._lock:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT * FROM hitl_handoffs WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def list_handoffs(self, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """List HITL handoff records, optionally filtered by status."""
        with self._lock:
            conn = self._get_conn()
            if status:
                rows = conn.execute(
                    "SELECT * FROM hitl_handoffs WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM hitl_handoffs ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]

    def clear(self) -> None:
        """Clear all handoff records (intended for tests)."""
        with self._lock:
            conn = self._get_conn()
            conn.execute("DELETE FROM hitl_handoffs")
            conn.commit()


handoff_store = HandoffStore()
