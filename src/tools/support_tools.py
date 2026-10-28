"""Customer Support Agent tools: merchant settlements, POS/decline diagnostics, and support tickets."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from src.config.settings import settings
from src.observability.logger import get_logger
from src.observability.tracer import traceable_step

logger = get_logger("tools.support_tools")

_RUNTIME_CREATED_TICKETS: dict[str, list[dict[str, Any]]] = {}


def load_merchants_db(path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    """Load the merchant dictionary keyed by user_id from data/merchants.json."""
    resolved = settings.resolve_path(str(path or settings.merchants_data_path))
    if not resolved.exists():
        logger.warning("merchants_db_not_found", path=str(resolved))
        return {}
    raw = json.loads(resolved.read_text(encoding="utf-8"))
    return dict(raw.get("merchants") or {})


@traceable_step(name="get_merchant_settlement_status", run_type="tool")
def get_merchant_settlement_status(user_id: str) -> dict[str, Any]:
    """Retrieve a merchant's settlement schedule, yesterday's sales deposit status, and bank details."""
    clean_uid = (user_id or "").strip()
    merchants = load_merchants_db()
    record = merchants.get(clean_uid)

    if record is None:
        summary = (
            f"Merchant '{clean_uid}' was not found in the active settlement ledger. "
            "Standard Getnet settlement timelines: Debit sales settle in 1 business day (D+1); "
            "Credit sales settle in 30 days (or D+1 / D+2 with Antecipação Automática / Plano Receba Já); "
            "Pix sales settle instantly or within the same business day into the registered domicílio bancário."
        )
        return {
            "tool_name": "get_merchant_settlement_status",
            "found": False,
            "user_id": clean_uid,
            "status": "MERCHANT_NOT_FOUND",
            "summary": summary,
            "general_settlement_rules": {
                "debit": "1 business day (D+1)",
                "credit_single": "30 days standard, or D+1/D+2 with Plano Receba Já (Antecipação)",
                "credit_installments": "Every 30 days per installment, or upfront in D+1/D+2 with Antecipação",
                "crediario": "2 business days (D+2)",
                "pix": "Instant / same-day settlement to registered domicílio bancário",
            },
            "source": "Getnet Settlement & Receivables Engine (data/merchants.json)",
        }

    settlement = record.get("settlement") or {}
    bank = settlement.get("bank_account") or {}
    summary = (
        f"Merchant {record.get('merchant_name')} ({clean_uid}) — Plan: {record.get('settlement_plan')}. "
        f"Yesterday's sales: R$ {settlement.get('yesterday_sales_gross_brl', 0.0):,.2f} gross "
        f"(R$ {settlement.get('yesterday_sales_net_brl', 0.0):,.2f} net across "
        f"{settlement.get('yesterday_transactions_count', 0)} transactions). "
        f"Deposit status: {settlement.get('deposit_status')} — Expected deposit: "
        f"{settlement.get('expected_deposit_date')} ({settlement.get('expected_deposit_window')}) "
        f"into {bank.get('bank_name')} (branch {bank.get('branch')}, account {bank.get('account_masked')})."
    )
    return {
        "tool_name": "get_merchant_settlement_status",
        "found": True,
        "user_id": clean_uid,
        "merchant_name": record.get("merchant_name"),
        "account_status": record.get("account_status"),
        "settlement_plan": record.get("settlement_plan"),
        "settlement": settlement,
        "summary": summary,
        "source": "Getnet Settlement & Receivables Engine (data/merchants.json)",
    }


@traceable_step(name="diagnose_pos_and_transactions", run_type="tool")
def diagnose_pos_and_transactions(
    user_id: str,
    issue_type: str = "all",
) -> dict[str, Any]:
    """Inspect a merchant's POS terminal connectivity telemetry and recent transaction decline codes."""
    clean_uid = (user_id or "").strip()
    norm_issue = (issue_type or "all").lower().strip()
    merchants = load_merchants_db()
    record = merchants.get(clean_uid)

    if record is None:
        summary = (
            f"No active POS terminal telemetry found for user_id '{clean_uid}'. "
            "General Getnet troubleshooting: (1) For internet connectivity, reconnect to a 2.4GHz Wi-Fi "
            "network or toggle Airplane Mode to refresh the 4G SIM APN session, then restart the terminal; "
            "(2) For transaction decline errors, check the 2-digit ISO-8583 code on screen (Code 51 = "
            "Insufficient Funds/Limit on cardholder's bank; Code 05 = Do Not Honor / blocked by issuer; "
            "Code 55 = Invalid PIN)."
        )
        return {
            "tool_name": "diagnose_pos_and_transactions",
            "found": False,
            "user_id": clean_uid,
            "issue_type": norm_issue,
            "status": "MERCHANT_NOT_FOUND",
            "summary": summary,
            "standard_troubleshooting": {
                "connectivity": [
                    "Connect to a 2.4GHz Wi-Fi network instead of 5GHz.",
                    "Refresh the 3G/4G SIM connection or restart the terminal.",
                    "Run Administrative > Connection Test on the terminal menu.",
                ],
                "decline_codes": {
                    "51": "Insufficient funds or credit limit on the customer's card.",
                    "05": "Do Not Honor — blocked by the customer's card-issuing bank.",
                    "55": "Incorrect card PIN entered by the customer.",
                },
            },
            "source": "Getnet POS Telemetry & ISO-8583 Switch Diagnostics (data/merchants.json)",
        }

    pos = record.get("pos_terminal") or {}
    conn = pos.get("connectivity") or {}
    declines = list(record.get("recent_declines") or [])

    parts: list[str] = [
        f"Terminal {pos.get('terminal_id')} ({pos.get('model')}, SN: {pos.get('serial_number')})"
    ]
    if norm_issue in ("all", "connectivity", "internet", "network", "wifi"):
        parts.append(
            f"Connectivity Status: {conn.get('current_status')} | "
            f"Wi-Fi: {conn.get('wifi_status')} | "
            f"4G SIM: {conn.get('sim_4g_status')} | "
            f"Recommended Steps: {' '.join(conn.get('troubleshooting_steps') or [])}"
        )
    if norm_issue in ("all", "decline", "transaction", "error"):
        if declines:
            latest = declines[0]
            parts.append(
                f"Latest Transaction Decline ({latest.get('transaction_id')}, R$ {latest.get('amount_brl', 0.0):,.2f} "
                f"on {latest.get('payment_method')}): {latest.get('error_label')}. "
                f"Cause: {latest.get('cause_explanation')} "
                f"Resolution Steps: {' '.join(latest.get('resolution_steps') or [])}"
            )
        else:
            parts.append("No recent transaction decline errors recorded on the switch.")

    return {
        "tool_name": "diagnose_pos_and_transactions",
        "found": True,
        "user_id": clean_uid,
        "merchant_name": record.get("merchant_name"),
        "issue_type": norm_issue,
        "pos_terminal": pos,
        "connectivity": conn,
        "recent_declines": declines,
        "summary": " || ".join(parts),
        "source": "Getnet POS Telemetry & ISO-8583 Switch Diagnostics (data/merchants.json)",
    }


@traceable_step(name="manage_support_ticket", run_type="tool")
def manage_support_ticket(
    user_id: str,
    issue_summary: str = "Technical assistance / POS connectivity & transaction check",
    action: str = "check_or_create",
    category: str = "POS_TECHNICAL_SUPPORT",
) -> dict[str, Any]:
    """Check existing support tickets or open a new technical support / terminal swap ticket."""
    clean_uid = (user_id or "").strip() or "anonymous"
    norm_action = (action or "check_or_create").lower().strip()
    merchants = load_merchants_db()
    record = merchants.get(clean_uid)

    existing_tickets: list[dict[str, Any]] = []
    if record is not None:
        existing_tickets.extend(record.get("tickets") or [])
    existing_tickets.extend(_RUNTIME_CREATED_TICKETS.get(clean_uid, []))

    created_ticket: dict[str, Any] | None = None
    if norm_action in ("create", "open", "check_or_create"):
        digest = hashlib.md5(f"{clean_uid}:{issue_summary}".encode("utf-8")).hexdigest()[:6].upper()
        ticket_id = f"TCK-2026-{digest}"
        created_ticket = {
            "ticket_id": ticket_id,
            "user_id": clean_uid,
            "status": "OPEN_IN_PROGRESS",
            "category": category,
            "summary": issue_summary,
            "sla_target": "Remote APN/Switch reset within 2h; onsite terminal replacement within 24h if hardware fault persists",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _RUNTIME_CREATED_TICKETS.setdefault(clean_uid, []).append(created_ticket)
        existing_tickets.append(created_ticket)

    summary = (
        f"Support Ticket Protocol {created_ticket['ticket_id']} registered for {clean_uid} "
        f"({created_ticket['summary']}). SLA: {created_ticket['sla_target']}."
        if created_ticket
        else f"Retrieved {len(existing_tickets)} ticket(s) for merchant {clean_uid}."
    )

    return {
        "tool_name": "manage_support_ticket",
        "user_id": clean_uid,
        "merchant_found": record is not None,
        "action": norm_action,
        "created_ticket": created_ticket,
        "tickets": existing_tickets,
        "summary": summary,
        "source": "Getnet Technical Support & Field Service CRM",
    }


@tool("get_merchant_settlement_status")
def get_merchant_settlement_status_tool(user_id: str) -> dict[str, Any]:
    """Retrieve a merchant's settlement schedule, yesterday's sales deposit window, and registered bank account."""
    return get_merchant_settlement_status(user_id=user_id)


@tool("diagnose_pos_and_transactions")
def diagnose_pos_and_transactions_tool(user_id: str, issue_type: str = "all") -> dict[str, Any]:
    """Diagnose POS card machine internet connectivity and recent transaction decline error codes for a user_id."""
    return diagnose_pos_and_transactions(user_id=user_id, issue_type=issue_type)


@tool("manage_support_ticket")
def manage_support_ticket_tool(
    user_id: str,
    issue_summary: str = "Technical assistance request",
    action: str = "check_or_create",
) -> dict[str, Any]:
    """Open or check a technical support ticket for a merchant user_id."""
    return manage_support_ticket(user_id=user_id, issue_summary=issue_summary, action=action)
