"""Human Escalation & Handoff Agent tools for complex, disputed, or low-confidence requests."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from langchain_core.tools import tool

from src.observability.tracer import traceable_step


@traceable_step(name="dispatch_human_handoff", run_type="tool")
def dispatch_human_handoff(
    user_id: str,
    reason: str,
    conversation_summary: str,
    priority: str = "HIGH",
    confidence_score: float = 0.45,
) -> dict[str, Any]:
    """Create a structured human operator handoff ticket and route the conversation to a specialist queue."""
    clean_uid = (user_id or "anonymous").strip()
    digest = hashlib.md5(f"{clean_uid}:{reason}:{conversation_summary}".encode("utf-8")).hexdigest()[:6].upper()
    protocol_id = f"ESC-GN-{digest}"
    norm_priority = priority.upper().strip() if priority else "HIGH"
    queue_name = (
        "Getnet Tier-2 Acquiring & Risk Specialist Desk"
        if norm_priority in ("HIGH", "CRITICAL", "URGENT")
        else "Getnet Human Customer Care Desk"
    )
    estimated_wait_minutes = 2 if norm_priority in ("HIGH", "CRITICAL", "URGENT") else 5

    summary = (
        f"Human Escalation Protocol {protocol_id} dispatched to '{queue_name}' "
        f"(Priority: {norm_priority}, Estimated Wait: ~{estimated_wait_minutes} min) "
        f"for merchant '{clean_uid}'. Reason: {reason}."
    )
    return {
        "tool_name": "dispatch_human_handoff",
        "protocol_id": protocol_id,
        "user_id": clean_uid,
        "priority": norm_priority,
        "assigned_queue": queue_name,
        "estimated_wait_minutes": estimated_wait_minutes,
        "confidence_score": round(float(confidence_score), 3),
        "handoff_required": True,
        "reason": reason,
        "conversation_summary": conversation_summary,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "source": "Getnet Omnichannel Human Handoff Router",
    }


@tool("dispatch_human_handoff")
def dispatch_human_handoff_tool(
    user_id: str,
    reason: str,
    conversation_summary: str,
    priority: str = "HIGH",
) -> dict[str, Any]:
    """Dispatch the merchant's conversation to a human Getnet support specialist with full context."""
    return dispatch_human_handoff(
        user_id=user_id,
        reason=reason,
        conversation_summary=conversation_summary,
        priority=priority,
    )
