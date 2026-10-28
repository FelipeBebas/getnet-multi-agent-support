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
    assert body["routed_agents"] == scenario["expected_agents"], (
        f"Scenario {scenario['id']} routed to {body['routed_agents']} "
        f"instead of {scenario['expected_agents']}"
    )

    for expected_tool in scenario["expected_tools"]:
        assert expected_tool in body["tools_used"], (
            f"Scenario {scenario['id']} missing expected tool '{expected_tool}' "
            f"in {body['tools_used']}"
        )

    assert body["guardrail_triggered"] is scenario["expect_guardrail_block"]
    assert body["handoff_required"] is scenario["expect_handoff"]

    answer_lower = body["response"].lower()
    for kw in scenario["expected_keywords"]:
        assert kw.lower() in answer_lower, (
            f"Scenario {scenario['id']} response missing expected keyword '{kw}'"
        )
