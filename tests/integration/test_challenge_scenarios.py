"""Integration test suite verifying all 10 official challenge scenarios + hybrid, escalation, and guardrail cases."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.config.settings import settings


def _load_eval_scenarios() -> list[dict[str, Any]]:
    path = settings.resolve_path(settings.eval_dataset_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data.get("scenarios") or [])


@pytest.mark.parametrize(
    "scenario",
    _load_eval_scenarios(),
    ids=lambda s: f"{s['id']}_{s['category']}",
)
def test_end_to_end_challenge_scenario(
    api_client: TestClient,
    scenario: dict[str, Any],
) -> None:
    """Execute each scenario through POST /chat and verify routing, tool calls, and answer groundedness."""
    resp = api_client.post(
        "/chat",
        json={
            "message": scenario["message"],
            "user_id": scenario["user_id"],
        },
    )
    assert resp.status_code == 200
    body = resp.json()

    assert body["user_id"] == scenario["user_id"]
    for expected_agent in scenario["expected_agents"]:
        assert expected_agent in body["routed_agents"], (
            f"Scenario {scenario['id']} missing agent '{expected_agent}' "
            f"in {body['routed_agents']}"
        )

    for expected_tool in scenario["expected_tools"]:
        assert expected_tool in body["tools_used"], (
            f"Scenario {scenario['id']} missing expected tool '{expected_tool}' "
            f"in {body['tools_used']}"
        )

    assert body["guardrail_triggered"] is scenario["expect_guardrail_block"]

    answer_lower = body["response"].lower()
    norm_answer = answer_lower.replace(".", "").replace(",", "").replace(" ", "")
    matched_kws = [
        kw for kw in scenario["expected_keywords"]
        if kw.lower() in answer_lower or kw.lower().replace(".", "").replace(",", "").replace(" ", "") in norm_answer
    ]
    assert len(matched_kws) >= max(1, len(scenario["expected_keywords"]) // 2), (
        f"Scenario {scenario['id']} response matched only {matched_kws} "
        f"out of {scenario['expected_keywords']}. Response: {body['response'][:200]}"
    )
