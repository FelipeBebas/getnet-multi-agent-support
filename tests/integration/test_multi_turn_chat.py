"""Integration tests for multi-turn conversational chat, contextual rewriting, and session memory."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_multi_turn_currency_followup_chain(api_client: TestClient) -> None:
    """Verify that an elliptical follow-up like 'what about yen?' succeeds without 500 errors."""
    user_id = "test_fx_multi_turn_user"
    api_client.delete(f"/chat/history/{user_id}")

    # Turn 1: Euro exchange rate
    turn1_resp = api_client.post(
        "/chat",
        json={"message": "What's the euro exchange rate today?", "user_id": user_id},
    )
    assert turn1_resp.status_code == 200
    t1_data = turn1_resp.json()
    assert "knowledge_agent" in t1_data["routed_agents"]
    assert "web_search_general" in t1_data["tools_used"]
    assert "EUR" in t1_data["response"] or "Euro" in t1_data["response"]
    assert len(t1_data.get("chat_history", [])) == 2

    # Turn 2: Elliptical follow-up "what about yen?"
    turn2_resp = api_client.post(
        "/chat",
        json={"message": "what about yen?", "user_id": user_id},
    )
    assert turn2_resp.status_code == 200
    t2_data = turn2_resp.json()
    assert "knowledge_agent" in t2_data["routed_agents"]
    assert "web_search_general" in t2_data["tools_used"]
    # Check that Yen is answered and not Euro repeated blindly
    assert any(term in t2_data["response"].lower() for term in ("yen", "jpy", "iene"))
    assert len(t2_data.get("chat_history", [])) == 4


def test_multi_turn_pos_pricing_followup_chain(api_client: TestClient) -> None:
    """Verify conversational context resolution for POS product follow-ups ('quanto custa ela?')."""
    user_id = "test_pos_multi_turn_user"
    api_client.delete(f"/chat/history/{user_id}")

    # Turn 1: Product comparison
    turn1_resp = api_client.post(
        "/chat",
        json={
            "message": "What's the difference between the Get Clássica and the Get Smart?",
            "user_id": user_id,
        },
    )
    assert turn1_resp.status_code == 200
    t1_data = turn1_resp.json()
    assert "knowledge_agent" in t1_data["routed_agents"]

    # Turn 2: Elliptical pronoun follow-up
    turn2_resp = api_client.post(
        "/chat",
        json={"message": "quanto custa ela?", "user_id": user_id},
    )
    assert turn2_resp.status_code == 200
    t2_data = turn2_resp.json()
    assert "knowledge_agent" in t2_data["routed_agents"]
    assert t2_data["guardrail_triggered"] is False
    assert len(t2_data.get("chat_history", [])) == 4


def test_multi_turn_rates_followup_chain(api_client: TestClient) -> None:
    """Verify follow-up inquiries on acquiring rates ('e no débito?')."""
    user_id = "test_rates_multi_turn_user"
    api_client.delete(f"/chat/history/{user_id}")

    # Turn 1: Pix rates
    turn1_resp = api_client.post(
        "/chat",
        json={"message": "Qual a taxa do Pix na maquininha Getnet?", "user_id": user_id},
    )
    assert turn1_resp.status_code == 200
    t1_data = turn1_resp.json()
    assert "knowledge_agent" in t1_data["routed_agents"]

    # Turn 2: Elliptical question on debit rates
    turn2_resp = api_client.post(
        "/chat",
        json={"message": "e no débito?", "user_id": user_id},
    )
    assert turn2_resp.status_code == 200
    t2_data = turn2_resp.json()
    assert "knowledge_agent" in t2_data["routed_agents"]
    assert len(t2_data.get("chat_history", [])) == 4


def test_multi_turn_session_isolation_and_delete(api_client: TestClient) -> None:
    """Verify session isolation between distinct users and deletion endpoint."""
    user_a = "user_isolation_alpha"
    user_b = "user_isolation_beta"

    api_client.delete(f"/chat/history/{user_a}")
    api_client.delete(f"/chat/history/{user_b}")

    api_client.post(
        "/chat",
        json={"message": "What is the euro rate?", "user_id": user_a},
    )
    api_client.post(
        "/chat",
        json={"message": "Qual a taxa do Pix?", "user_id": user_b},
    )

    # Check histories independently
    hist_a = api_client.get(f"/chat/history/{user_a}").json()
    hist_b = api_client.get(f"/chat/history/{user_b}").json()

    assert hist_a["turns_count"] == 2
    assert "euro" in hist_a["messages"][0]["content"].lower()
    assert hist_b["turns_count"] == 2
    assert "pix" in hist_b["messages"][0]["content"].lower()

    # Clear user A
    del_res = api_client.delete(f"/chat/history/{user_a}")
    assert del_res.status_code == 200

    assert api_client.get(f"/chat/history/{user_a}").json()["turns_count"] == 0
    assert api_client.get(f"/chat/history/{user_b}").json()["turns_count"] == 2
