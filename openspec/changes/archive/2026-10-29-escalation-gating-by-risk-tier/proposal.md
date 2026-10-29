# Proposal

## Why

Currently, when the Knowledge Retrieval Agent (`Agent 2`) answers out-of-corpus or general business queries using its DuckDuckGo search fallback or epistemic humility, it appropriately caps its resolution confidence at `0.45` to prevent hallucinations. However, the LangGraph orchestrator's dispatch logic (`_dispatch_next_from_queue`) evaluates low confidence (`confidence < 0.60`) blindly across all domain queries, automatically triggering the Human Escalation Agent (`Agent 4`) and generating support tickets (`TCK-2026-...`).

This creates significant operational friction: benign informational queries (such as "Quando a Getnet foi fundada?" or "Quais os planos padrão?") waste costly human operator capacity and inflate the human ticket queue. We need to decouple statistical uncertainty from human ticket escalation by introducing a 3-tier business risk classification (`high`, `medium`, `low`) at the Router level, ensuring human handoff is strictly reserved for high/medium financial and transactional risk disputes or explicit human requests.

## What Changes

- **Router Plan Risk Classification**: Extend `RouterPlan` in `src/orchestration/state.py` with an explicit `risk_tier: Literal["high", "medium", "low"]` attribute (defaulting to `"low"` for backward compatibility).
- **Router Semantic Classification**: Update `src/agents/router_agent.py` to classify queries into risk tiers:
  - `high`: Financial loss, active fraud, chargebacks, disputed settlement, blocked hardware/terminals during sales.
  - `medium`: Ledger reconciliation, historical financial discrepancies, fee disputes, plan change negotiations.
  - `low`: Informational inquiries, general corporate trivia, product catalog, onboarding FAQs, portal navigation.
- **Conditional Escalation Gating in Graph**: Modify `_dispatch_next_from_queue` in `src/orchestration/graph.py` to evaluate both confidence and risk tier. When `confidence < settings.confidence_escalation_threshold`, escalation is triggered **only** if `risk_tier in ("high", "medium")` or if the user explicitly requested human assistance. For `low` risk queries with low confidence, the workflow completes with epistemic caveats and does not invoke `escalation_agent`.
- **Preserve Anti-Hallucination & Financial Guardrails**: Preserve existing low-confidence routing for financial ledger disputes (which are classified as `high` or `medium` risk), ensuring all existing red-teaming tests continue to trigger escalation as expected.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `guardrails-escalation`: Update the Human Escalation and Handoff Agent requirement to specify that low-confidence automatic escalation is gated by business risk tier (`high` or `medium`), preventing informational queries from generating human support tickets.

## Impact

- **Affected Code**:
  - `src/orchestration/state.py`: `RouterPlan` Pydantic model (`risk_tier` field).
  - `src/agents/router_agent.py`: Router prompt and JSON parser to emit and validate `risk_tier`.
  - `src/orchestration/graph.py`: `_dispatch_next_from_queue` conditional escalation check.
  - `tests/unit/test_router.py` & `tests/unit/test_orchestrator.py`: Unit tests validating risk-tier assignment and selective escalation behavior.
- **APIs & Dependencies**: No external breaking API changes; `risk_tier` defaults to `"low"` in `RouterPlan`, maintaining full backward compatibility with existing state dictionaries and mocks.
