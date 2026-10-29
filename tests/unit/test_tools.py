"""Unit tests for Knowledge Agent, Customer Support Agent, and Human Escalation Agent tools."""

from __future__ import annotations

from src.rag.ingest import load_markdown_corpus
from src.rag.vector_store import GetnetVectorStore
from src.tools.escalation_tools import (
    dispatch_human_handoff,
    dispatch_human_handoff_tool,
)
from src.tools.knowledge_tools import (
    retrieve_getnet_knowledge,
    retrieve_getnet_knowledge_tool,
    web_search_general,
    web_search_general_tool,
)
from src.tools.support_tools import (
    diagnose_pos_and_transactions,
    diagnose_pos_and_transactions_tool,
    get_merchant_settlement_status,
    get_merchant_settlement_status_tool,
    manage_support_ticket,
    manage_support_ticket_tool,
)


def test_retrieve_getnet_knowledge_grounded_product_query() -> None:
    """Verify retrieve_getnet_knowledge returns grounded chunks and citations for known products."""
    store = GetnetVectorStore(collection_name="test_tool_rag", ephemeral=True)
    store.ingest_chunks(load_markdown_corpus())

    res = retrieve_getnet_knowledge(
        "What's the difference between the Get Clássica and the Get Smart?",
        top_k=3,
        vector_store=store,
    )
    assert res["tool_name"] == "retrieve_getnet_knowledge"
    assert res["live_fallback_triggered"] is False
    assert res["top_similarity"] >= 0.50
    assert len(res["chunks"]) >= 1
    assert "https://site.getnet.com.br/maquininhas/" in res["sources"]


def test_retrieve_getnet_knowledge_live_domain_fallback_for_unlisted_product() -> None:
    """Verify retrieve_getnet_knowledge triggers live Getnet domain search when similarity is low."""
    store = GetnetVectorStore(collection_name="test_tool_fallback", ephemeral=True)
    store.ingest_chunks(load_markdown_corpus())

    res = retrieve_getnet_knowledge(
        "Quantum Holographic Satellite Orbit 2099",
        top_k=2,
        vector_store=store,
    )
    assert res["live_fallback_triggered"] is True
    assert len(res["live_fallback_results"]) >= 1
    assert len(res["sources"]) >= 1


def test_web_search_general_weather_porto_alegre() -> None:
    """Verify web_search_general handles Porto Alegre weather forecast scenario with local timezone."""
    from datetime import datetime, timedelta
    try:
        from zoneinfo import ZoneInfo
        city_now = datetime.now(ZoneInfo("America/Sao_Paulo"))
    except Exception:
        city_now = datetime.now().astimezone()

    valid_tomorrows = {
        (city_now + timedelta(days=1)).strftime("%Y-%m-%d"),
        (datetime.now().astimezone() + timedelta(days=1)).strftime("%Y-%m-%d"),
    }
    valid_todays = {
        city_now.strftime("%Y-%m-%d"),
        datetime.now().astimezone().strftime("%Y-%m-%d"),
    }

    res = web_search_general("What's the weather forecast in Porto Alegre tomorrow?")
    assert res["tool_name"] == "web_search_general"
    assert res["category"] == "weather"
    assert "Porto Alegre" in res["summary"]
    assert "°C" in res["summary"]
    assert res["target_date"] in valid_tomorrows
    assert len(res["sources"]) >= 1

    res_today = web_search_general("What's the weather forecast in Porto Alegre today?")
    assert res_today["category"] == "weather"
    assert res_today["target_date"] in valid_todays


def test_web_search_general_euro_exchange_rate() -> None:
    """Verify web_search_general handles Euro exchange rate scenario."""
    res = web_search_general("What's the euro exchange rate today?")
    assert res["tool_name"] == "web_search_general"
    assert res["category"] == "exchange_rate"
    assert "EUR" in res["summary"]
    assert "BRL" in res["summary"]
    assert len(res["sources"]) >= 1


def test_get_merchant_settlement_status_for_cliente1988_and_unknown() -> None:
    """Verify settlement lookup returns exact deposit window for cliente1988 and fallback for unknown."""
    res = get_merchant_settlement_status("cliente1988")
    assert res["tool_name"] == "get_merchant_settlement_status"
    assert res["found"] is True
    assert res["user_id"] == "cliente1988"
    assert res["settlement"]["yesterday_sales_net_brl"] == 4712.25
    assert "09:00 and 14:30 BRT" in res["summary"]

    unknown = get_merchant_settlement_status("unknown_user_404")
    assert unknown["found"] is False
    assert unknown["status"] == "MERCHANT_NOT_FOUND"
    assert "D+1" in unknown["summary"]


def test_diagnose_pos_and_transactions_for_cliente1988_and_unknown() -> None:
    """Verify POS connectivity and transaction decline diagnostics for cliente1988 and unknown."""
    conn_res = diagnose_pos_and_transactions("cliente1988", issue_type="connectivity")
    assert conn_res["tool_name"] == "diagnose_pos_and_transactions"
    assert conn_res["found"] is True
    assert "Get Smart" in conn_res["pos_terminal"]["model"]
    assert "2.4GHz" in conn_res["summary"]

    decline_res = diagnose_pos_and_transactions("cliente1988", issue_type="decline")
    assert decline_res["found"] is True
    assert len(decline_res["recent_declines"]) >= 1
    assert decline_res["recent_declines"][0]["iso8583_code"] == "51"
    assert "Code 51" in decline_res["summary"]

    unknown = diagnose_pos_and_transactions("unknown_user_404", issue_type="all")
    assert unknown["found"] is False
    assert unknown["status"] == "MERCHANT_NOT_FOUND"
    assert "51" in unknown["standard_troubleshooting"]["decline_codes"]


def test_manage_support_ticket_and_escalation_handoff_tools() -> None:
    """Verify support ticket creation and human escalation handoff protocol generation."""
    tck = manage_support_ticket(
        user_id="cliente1988",
        issue_summary="POS Wi-Fi and 4G APN intermittent drop",
        action="create",
    )
    assert tck["tool_name"] == "manage_support_ticket"
    assert tck["merchant_found"] is True
    assert tck["created_ticket"] is not None
    assert tck["created_ticket"]["ticket_id"].startswith("TCK-2026-")

    esc = dispatch_human_handoff(
        user_id="cliente1988",
        reason="Merchant requested human supervisor for contested chargeback",
        conversation_summary="Customer asked to escalate dispute to human operator",
        priority="HIGH",
        confidence_score=0.40,
    )
    assert esc["tool_name"] == "dispatch_human_handoff"
    assert esc["handoff_required"] is True
    assert esc["protocol_id"].startswith("ESC-GN-")


def test_all_langchain_tool_wrappers_invoke() -> None:
    """Verify all 6 LangChain @tool wrappers execute cleanly."""
    kb_out = retrieve_getnet_knowledge_tool.invoke(
        {"query": "Can I sell through WhatsApp using the Payment Link?"}
    )
    assert kb_out["tool_name"] == "retrieve_getnet_knowledge"

    web_out = web_search_general_tool.invoke(
        {"query": "What's the euro exchange rate today?"}
    )
    assert web_out["tool_name"] == "web_search_general"

    stl_out = get_merchant_settlement_status_tool.invoke({"user_id": "cliente1988"})
    assert stl_out["found"] is True

    diag_out = diagnose_pos_and_transactions_tool.invoke(
        {"user_id": "cliente1988", "issue_type": "all"}
    )
    assert diag_out["found"] is True

    tck_out = manage_support_ticket_tool.invoke(
        {"user_id": "cliente1988", "issue_summary": "Check tickets", "action": "list"}
    )
    assert tck_out["tool_name"] == "manage_support_ticket"

    esc_out = dispatch_human_handoff_tool.invoke(
        {
            "user_id": "cliente1988",
            "reason": "Need specialist",
            "conversation_summary": "Escalation test",
            "priority": "HIGH",
        }
    )
    assert esc_out["handoff_required"] is True


def test_web_search_exchange_rate_multi_currency_support() -> None:
    """Verify exchange rate querying handles EUR, JPY, USD, and GBP with robust fallbacks."""
    from src.tools.knowledge_tools import _detect_currency, web_search_general

    # Currency detection
    assert _detect_currency("What is the euro exchange rate today?")[0] == "EUR"
    assert _detect_currency("what about yen?")[0] == "JPY"
    assert _detect_currency("qual a cotação do dólar hoje?")[0] == "USD"
    assert _detect_currency("cotação da libra esterlina gbp")[0] == "GBP"

    # Execution for Yen
    yen_res = web_search_general("what about yen?")
    assert yen_res["tool_name"] == "web_search_general"
    assert yen_res["category"] == "exchange_rate"
    assert yen_res["currency"] == "JPY"
    assert "JPY" in yen_res["summary"]
    assert "BRL" in yen_res["summary"]

    # Execution for Euro
    eur_res = web_search_general("Euro exchange rate today")
    assert eur_res["category"] == "exchange_rate"
    assert eur_res["currency"] == "EUR"
    assert "EUR" in eur_res["summary"]


def test_web_search_general_resilience_on_empty_hits(monkeypatch) -> None:
    """Verify web_search_general gracefully handles empty results without NameError."""
    from src.tools import knowledge_tools

    # Mock all web search providers to return empty list
    monkeypatch.setattr(knowledge_tools, "_tavily_search", lambda *args, **kwargs: [])
    monkeypatch.setattr(knowledge_tools, "_duckduckgo_search", lambda *args, **kwargs: [])
    monkeypatch.setattr(knowledge_tools, "_wikipedia_search", lambda *args, **kwargs: [])

    res = knowledge_tools.web_search_general("xyz123randomnonexistentquery999")
    assert res["tool_name"] == "web_search_general"
    assert res["verified_results"] is False
    assert res["results"] == []
    assert res["sources"] == []
