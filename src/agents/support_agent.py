"""Agent 3 — Customer Support Agent: executes merchant-scoped settlement, POS, and ticket tools."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from src.config.settings import settings
from src.observability.logger import get_logger
from src.observability.tracer import extract_token_usage, traceable_step
from src.orchestration.state import AgentStepOutput
from src.tools.support_tools import (
    diagnose_pos_and_transactions,
    get_merchant_settlement_status,
    manage_support_ticket,
)

logger = get_logger("agents.support_agent")

SUPPORT_SYSTEM_PROMPT = """You are Agent 3 (Customer Support Agent) of the Getnet Multi-Agent Support System.
Resolve the merchant's inquiry using the account and terminal diagnostic tool outputs retrieved for their `user_id`.
- For settlement inquiries, state the exact gross/net sales amount from yesterday, the deposit status, date, time window, and bank account details.
- For POS internet connectivity issues, identify the merchant's registered terminal model and provide the step-by-step Wi-Fi (2.4GHz vs 5GHz), 4G SIM APN refresh, and reboot instructions.
- For transaction decline errors, specify the exact ISO-8583 error code on the latest transaction (e.g., Code 51 — Insufficient Funds), explain that it originates from the cardholder's issuing bank rather than a terminal defect, and provide actionable next steps."""


def _synthesize_support_fallback(
    user_id: str,
    settlement_data: dict[str, Any] | None,
    diag_data: dict[str, Any] | None,
    ticket_data: dict[str, Any] | None,
) -> str:
    """Build a detailed, accurate support answer directly from the executed domain tools."""
    sections: list[str] = []

    if settlement_data is not None:
        if settlement_data.get("found"):
            stl = settlement_data.get("settlement") or {}
            bank = stl.get("bank_account") or {}
            sections.append(
                f"**Settlement Status for `{user_id}` ({settlement_data.get('merchant_name')})**:\n"
                f"- **Yesterday's Sales**: **R$ {stl.get('yesterday_sales_net_brl', 0.0):,.2f} net** "
                f"(R$ {stl.get('yesterday_sales_gross_brl', 0.0):,.2f} gross across "
                f"{stl.get('yesterday_transactions_count', 0)} transactions).\n"
                f"- **Deposit Schedule**: **{stl.get('expected_deposit_date')}** "
                f"(**{stl.get('expected_deposit_window')}**) under your **{settlement_data.get('settlement_plan')}**.\n"
                f"- **Destination Account**: {bank.get('bank_name')} — Branch `{bank.get('branch')}`, "
                f"Account `{bank.get('account_masked')}` ({stl.get('deposit_status')})."
            )
        else:
            sections.append(str(settlement_data.get("summary") or ""))

    if diag_data is not None:
        if diag_data.get("found"):
            pos = diag_data.get("pos_terminal") or {}
            conn = diag_data.get("connectivity") or {}
            declines = diag_data.get("recent_declines") or []
            issue_type = diag_data.get("issue_type", "all")

            if issue_type in ("connectivity", "all"):
                steps_str = "\n".join(
                    f"  {s}" for s in (conn.get("troubleshooting_steps") or [])
                )
                sections.append(
                    f"**POS Connectivity Diagnostics for `{user_id}` — Terminal `{pos.get('terminal_id')}` "
                    f"({pos.get('model')})**:\n"
                    f"- **Current Telemetry**: `{conn.get('current_status')}` | Wi-Fi: {conn.get('wifi_status')} | "
                    f"4G SIM: {conn.get('sim_4g_status')}.\n"
                    f"- **Recommended Troubleshooting Steps**:\n{steps_str}"
                )

            if issue_type in ("decline", "all") and declines:
                latest = declines[0]
                res_steps = "\n".join(
                    f"  {s}" for s in (latest.get("resolution_steps") or [])
                )
                sections.append(
                    f"**Transaction Decline Diagnostics for `{user_id}` — Terminal `{pos.get('terminal_id')}` "
                    f"({pos.get('model')})**:\n"
                    f"- **Last Declined Transaction**: `{latest.get('transaction_id')}` "
                    f"(R$ {latest.get('amount_brl', 0.0):,.2f} on {latest.get('payment_method')}, "
                    f"Card `{latest.get('card_masked')}`).\n"
                    f"- **Decline Code Identified**: **{latest.get('error_label')}**.\n"
                    f"- **Cause**: {latest.get('cause_explanation')}\n"
                    f"- **How to Resolve**:\n{res_steps}"
                )
        else:
            sections.append(str(diag_data.get("summary") or ""))

    if ticket_data is not None:
        sections.append(f"**Support Ticket Update**: {ticket_data.get('summary')}")

    return "\n\n".join(s for s in sections if s).strip()


@traceable_step(name="customer_support_agent_run", run_type="chain")
def run_customer_support_agent(
    message: str,
    user_id: str,
    sub_intent: str = "all",
    chat_history: list[dict[str, str]] | None = None,
) -> AgentStepOutput:
    """Execute Agent 3 (Customer Support Agent) with >=3 specialized merchant tools."""
    tools_used: list[str] = []
    sources: list[str] = []
    raw_data: dict[str, Any] = {}

    settlement_data: dict[str, Any] | None = None
    diag_data: dict[str, Any] | None = None
    ticket_data: dict[str, Any] | None = None

    if sub_intent in ("settlement", "all", "none"):
        settlement_data = get_merchant_settlement_status(user_id=user_id)
        tools_used.append("get_merchant_settlement_status")
        sources.append(str(settlement_data.get("source")))
        raw_data["settlement"] = settlement_data

    if sub_intent == "pos_connectivity":
        diag_data = diagnose_pos_and_transactions(user_id=user_id, issue_type="connectivity")
        tools_used.append("diagnose_pos_and_transactions")
        sources.append(str(diag_data.get("source")))
        raw_data["diagnostics"] = diag_data
    elif sub_intent == "transaction_decline":
        diag_data = diagnose_pos_and_transactions(user_id=user_id, issue_type="decline")
        tools_used.append("diagnose_pos_and_transactions")
        sources.append(str(diag_data.get("source")))
        raw_data["diagnostics"] = diag_data
    elif sub_intent == "all":
        diag_data = diagnose_pos_and_transactions(user_id=user_id, issue_type="all")
        tools_used.append("diagnose_pos_and_transactions")
        sources.append(str(diag_data.get("source")))
        raw_data["diagnostics"] = diag_data

    if sub_intent == "ticket" or "ticket" in message.lower() or "chamado" in message.lower():
        ticket_data = manage_support_ticket(
            user_id=user_id,
            issue_summary=message[:120],
            action="check_or_create",
        )
        tools_used.append("manage_support_ticket")
        sources.append(str(ticket_data.get("source")))
        raw_data["ticket"] = ticket_data

    dedup_sources = list(dict.fromkeys(s for s in sources if s))
    fallback_text = _synthesize_support_fallback(
        user_id=user_id,
        settlement_data=settlement_data,
        diag_data=diag_data,
        ticket_data=ticket_data,
    )

    confidence = 0.95
    if (settlement_data and not settlement_data.get("found")) or (
        diag_data and not diag_data.get("found")
    ):
        confidence = 0.78

    if settings.use_live_llm:
        try:  # pragma: no cover
            llm = ChatOpenAI(
                model=settings.openai_model,
                temperature=settings.openai_temperature_agent,
                api_key=settings.openai_api_key,
                timeout=12.0,
            )
            resp = llm.invoke(
                [
                    SystemMessage(content=SUPPORT_SYSTEM_PROMPT),
                    HumanMessage(
                        content=(
                            f"Merchant user_id: {user_id}\n"
                            f"Tool Outputs:\n{fallback_text}\n\n"
                            f"Merchant Message: {message}"
                        )
                    ),
                ]
            )
            llm_text = str(resp.content).strip()
            token_usage = extract_token_usage(resp)
            if llm_text:
                return AgentStepOutput(
                    agent_name="customer_support_agent",
                    content=llm_text,
                    tools_used=tools_used,
                    sources=dedup_sources,
                    confidence=confidence,
                    raw_data=raw_data,
                    token_usage=token_usage,
                )
        except Exception as exc:  # pragma: no cover
            logger.warning("support_agent_llm_fallback", error=str(exc))

    return AgentStepOutput(
        agent_name="customer_support_agent",
        content=fallback_text,
        tools_used=tools_used,
        sources=dedup_sources,
        confidence=confidence,
        raw_data=raw_data,
    )
