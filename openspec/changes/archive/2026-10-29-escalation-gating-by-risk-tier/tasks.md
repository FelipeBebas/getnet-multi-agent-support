# Tasks

## 1. Schema & Router Classification

- [x] 1.1 Extend `RouterPlan` in `src/orchestration/state.py` with `risk_tier: Literal["high", "medium", "low"] = "low"` and verify model instantiation with and without `risk_tier`
- [x] 1.2 Update prompt and JSON parsing in `src/agents/router_agent.py` to classify queries into risk tiers with deterministic keyword overrides for critical financial tokens (`chargeback`, `estorno`, `fraude`, `bloqueio`, `balanço`, `faturamento`)
- [x] 1.3 Add unit tests in `tests/unit/test_router.py` covering risk tier classification for high, medium, and low risk prompts and verify unit tests pass

## 2. Graph Conditional Escalation Gating

- [x] 2.1 Update `_dispatch_next_from_queue` in `src/orchestration/graph.py` to gate low-confidence escalation on `risk_tier in ("high", "medium")`, completing the workflow without human escalation for `low` risk queries
- [x] 2.2 Add unit tests in `tests/unit/test_orchestrator.py` verifying that low confidence on `low` risk queries completes without calling `escalation_agent` and keeps `handoff_required=False`
- [x] 2.3 Verify that low confidence on `high` or `medium` risk queries (including ledger inquiries like `faturamento e balanço exato`) continues to invoke `escalation_agent` and sets `handoff_required=True`

## 3. End-to-End Regression Verification

- [x] 3.1 Execute the full test suite (`pytest`) to verify all 81 tests pass cleanly without regression
- [x] 3.2 Update `POST_DELIVERY_IMPROVEMENTS.md` to document the resolved risk-gated escalation architecture

## Workflow follow-up

- Archive the change after implementation is verified with `/opsx-archive`.
