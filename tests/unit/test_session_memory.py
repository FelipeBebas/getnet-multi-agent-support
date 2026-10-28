"""Unit tests for in-memory session store and multi-turn conversational history."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.orchestration.session_store import SessionStore, session_store


def test_session_store_append_and_retrieve() -> None:
    store = SessionStore(max_history_turns=3)
    user = "merchant_test_1"

    store.add_message(user, "user", "Qual a taxa do Pix?")
    store.add_message(user, "assistant", "A taxa de Pix é 0.99% com liquidação imediata.")

    history = store.get_history(user)
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "Qual a taxa do Pix?"
    assert history[1]["role"] == "assistant"
    assert "0.99%" in history[1]["content"]


def test_session_store_prunes_at_max_history() -> None:
    store = SessionStore(max_history_turns=2)  # max 4 messages
    user = "merchant_prune_test"

    for i in range(5):
        store.add_message(user, "user", f"Question {i}")
        store.add_message(user, "assistant", f"Answer {i}")

    history = store.get_history(user)
    # Should keep only the last 4 messages (last 2 turns)
    assert len(history) == 4
    assert history[0]["content"] == "Question 3"
    assert history[-1]["content"] == "Answer 4"


def test_session_store_format_history_for_prompt() -> None:
    store = SessionStore()
    user = "prompt_format_test"

    store.add_message(user, "user", "Qual a diferença da Clássica e Smart?")
    store.add_message(user, "assistant", "A Get Clássica imprime comprovante e a Smart roda Android.")

    prompt_str = store.format_history_for_prompt(user)
    assert "User: Qual a diferença da Clássica e Smart?" in prompt_str
    assert "Assistant: A Get Clássica imprime comprovante" in prompt_str


def test_session_store_clear() -> None:
    store = SessionStore()
    user1 = "u1"
    user2 = "u2"

    store.add_message(user1, "user", "Oi")
    store.add_message(user2, "user", "Olá")

    store.clear(user1)
    assert len(store.get_history(user1)) == 0
    assert len(store.get_history(user2)) == 1

    store.clear()
    assert len(store.get_history(user2)) == 0


def test_chat_history_endpoints() -> None:
    client = TestClient(app)
    user_id = "test_endpoint_user"

    # Seed message
    session_store.clear(user_id)
    session_store.add_message(user_id, "user", "Pergunta teste")
    session_store.add_message(user_id, "assistant", "Resposta teste")

    # GET /chat/history/{user_id}
    res = client.get(f"/chat/history/{user_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["user_id"] == user_id
    assert data["turns_count"] == 2
    assert len(data["messages"]) == 2

    # DELETE /chat/history/{user_id}
    del_res = client.delete(f"/chat/history/{user_id}")
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "cleared"

    # Verify cleared
    res_after = client.get(f"/chat/history/{user_id}")
    assert res_after.status_code == 200
    assert res_after.json()["turns_count"] == 0


def test_contextual_query_rewriter_fx_followup() -> None:
    from src.agents.router_agent import classify_and_route, rewrite_contextual_query

    history = [
        {"role": "user", "content": "What's the euro exchange rate today?"},
        {"role": "assistant", "content": "The Euro rate is 6.12 BRL today."},
    ]

    rewritten = rewrite_contextual_query("what about yen?", history)
    assert "Yen" in rewritten
    assert "exchange rate" in rewritten.lower()

    plan = classify_and_route("what about yen?", user_id="cliente1988", chat_history=history)
    assert plan.primary_intent == "knowledge"
    assert plan.knowledge_sub_intent == "external_web_search"
    assert "knowledge_agent" in plan.agent_queue
    assert "Yen" in plan.rewritten_query


def test_contextual_query_rewriter_terminal_followup() -> None:
    from src.agents.router_agent import classify_and_route, rewrite_contextual_query

    history = [
        {"role": "user", "content": "What's the difference between the Get Clássica and the Get Smart?"},
        {"role": "assistant", "content": "Get Clássica prints receipts and Get Smart runs Android."},
    ]

    rewritten = rewrite_contextual_query("quanto custa ela?", history)
    assert "Get Clássica" in rewritten or "Get Smart" in rewritten or "taxas" in rewritten

    plan = classify_and_route("quanto custa ela?", user_id="cliente1988", chat_history=history)
    assert plan.primary_intent == "knowledge"
    assert "knowledge_agent" in plan.agent_queue


def test_contextual_query_rewriter_rates_followup() -> None:
    from src.agents.router_agent import classify_and_route, rewrite_contextual_query

    history = [
        {"role": "user", "content": "Qual a taxa do Pix na maquininha?"},
        {"role": "assistant", "content": "A taxa é 0.99%."},
    ]

    rewritten = rewrite_contextual_query("e no débito?", history)
    assert "débito" in rewritten.lower()

    plan = classify_and_route("e no débito?", user_id="cliente1988", chat_history=history)
    assert plan.primary_intent == "knowledge"
    assert "knowledge_agent" in plan.agent_queue


def test_contextual_query_rewriter_standalone_unchanged() -> None:
    from src.agents.router_agent import rewrite_contextual_query

    history = [
        {"role": "user", "content": "What's the euro exchange rate today?"},
    ]

    # Independent question should remain unchanged
    standalone = "When will the money from yesterday's sales be deposited?"
    rewritten = rewrite_contextual_query(standalone, history)
    assert rewritten == standalone
