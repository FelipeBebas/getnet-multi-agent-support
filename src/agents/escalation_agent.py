"""Agent 4 (Bonus Custom Agent) — Human Escalation & Handoff Specialist."""

from __future__ import annotations

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
) -> AgentStepOutput:
    """Execute Agent 4 (Human Escalation Agent) to register a priority handoff and support ticket."""
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
    content = (
        f"**Human Specialist Handoff Initiated (`{handoff['protocol_id']}`)**:\n"
        f"- **Assigned Queue**: {handoff['assigned_queue']} (Priority: `{handoff['priority']}`).\n"
        f"- **Linked Support Ticket**: `{created_tck.get('ticket_id', 'TCK-2026-ESC')}`.\n"
        f"- **Estimated Wait Time**: ~{handoff['estimated_wait_minutes']} minutes.\n"
        f"- **Context Forwarded**: Your account identifier (`{user_id}`) and conversation summary "
        "have been transferred so you do not need to repeat any information to our human specialist."
    )

    return AgentStepOutput(
        agent_name="escalation_agent",
        content=content,
        tools_used=["dispatch_human_handoff", "manage_support_ticket"],
        sources=[str(handoff.get("source")), str(ticket.get("source"))],
        confidence=confidence_score,
        handoff_required=True,
        raw_data={"handoff": handoff, "ticket": ticket},
    )
