"""Agent 4 (Bonus Custom Agent) — Human Escalation & Handoff Specialist."""

from __future__ import annotations

from typing import Any

from src.observability.tracer import traceable_step
from src.orchestration.state import AgentStepOutput
from src.tools.escalation_tools import dispatch_human_handoff
from src.tools.support_tools import manage_support_ticket


@traceable_step(name="escalation_agent_run", run_type="chain")
def run_escalation_agent(
    message: str,
    user_id: str,
    reason: str = "Explicit human specialist request or low automated confidence threshold",
    confidence_score: float = 0.48,
    human_decision: dict[str, Any] | None = None,
    existing_protocol_id: str | None = None,
    existing_ticket_id: str | None = None,
) -> AgentStepOutput:
    """Execute Agent 4 (Human Escalation Agent) to register handoff/ticket and optionally apply specialist decision."""
    if existing_protocol_id and existing_ticket_id:
        handoff = {
            "protocol_id": existing_protocol_id,
            "assigned_queue": "Getnet Tier-2 Acquiring & Risk Specialist Desk",
            "priority": "HIGH",
            "estimated_wait_minutes": 2,
            "source": "Getnet Omnichannel Human Handoff Router",
        }
        ticket = {
            "created_ticket": {"ticket_id": existing_ticket_id},
            "source": "Getnet Technical Support & Field Service CRM",
        }
        ticket_id = existing_ticket_id
    else:
        handoff = dispatch_human_handoff(
            user_id=user_id,
            reason=reason,
            conversation_summary=message[:200],
            priority="HIGH",
            confidence_score=confidence_score,
        )
        ticket = manage_support_ticket(
            user_id=user_id,
            issue_summary=f"[HUMAN ESCALATION] {message[:100]}",
            action="create",
            category="HUMAN_SPECIALIST_HANDOFF",
        )
        created_tck = ticket.get("created_ticket") or {}
        ticket_id = str(created_tck.get("ticket_id") or "TCK-2026-ESC")

    protocol_id = str(handoff["protocol_id"])

    if human_decision is not None:
        decision_label = str(human_decision.get("decision") or "approved")
        operator_note = str(human_decision.get("operator_note") or "").strip()
        operator_id = str(human_decision.get("operator_id") or "operator")
        content = (
            f"**Human Specialist Review Completed (`{protocol_id}` / `{ticket_id}`)**:\n"
            f"- **Decision**: `{decision_label}` (by `{operator_id}`).\n"
            f"- **Specialist Guidance**: {operator_note}\n"
        )
        raw_data = {
            "handoff": handoff,
            "ticket": ticket,
            "human_decision": human_decision,
        }
    else:
        content = (
            f"**Human Specialist Handoff Initiated (`{protocol_id}`)**:\n"
            f"- **Assigned Queue**: {handoff['assigned_queue']} (Priority: `{handoff['priority']}`).\n"
            f"- **Linked Support Ticket**: `{ticket_id}`.\n"
            f"- **Estimated Wait Time**: ~{handoff['estimated_wait_minutes']} minutes.\n"
            f"- **Status**: Awaiting human specialist review before final response synthesis.\n"
            f"- **Context Forwarded**: Your account identifier (`{user_id}`) and conversation summary "
            "have been transferred so you do not need to repeat any information to our human specialist."
        )
        raw_data = {"handoff": handoff, "ticket": ticket}

    return AgentStepOutput(
        agent_name="escalation_agent",
        content=content,
        tools_used=["dispatch_human_handoff", "manage_support_ticket"],
        sources=[str(handoff.get("source")), str(ticket.get("source"))],
        confidence=confidence_score,
        handoff_required=True,
        raw_data=raw_data,
    )
