# Design

## Context

See `proposal.md` for problem background and motivation.

Currently, `src/orchestration/graph.py` contains a flat confidence check:
```python
if conf < settings.confidence_escalation_threshold and "escalation_agent" not in routed:
    return "escalation_agent"
```
When `KnowledgeRetrievalAgent` (`Agent 2`) resolves an out-of-corpus query via DuckDuckGo search or states epistemic uncertainty, it sets `confidence = 0.45` to prevent hallucinations. Because this confidence is lower than `settings.confidence_escalation_threshold` (0.60), the orchestrator unconditionally routes the request to `HumanEscalationAgent` (`Agent 4`), opening a ticket (`TCK-2026-...`).

The goal of this design is to inject business risk awareness into the routing contract and execution graph, preventing informational queries from consuming human agent queues while preserving mandatory escalation for financial disputes.

## Goals / Non-Goals

**Goals:**
- Add `risk_tier: Literal["high", "medium", "low"]` to `RouterPlan` with default `"low"`.
- Instruct `RouterAgent` to categorize queries into `high`, `medium`, or `low` risk tiers based on business and financial impact.
- Implement an algorithmic keyword safety override in `RouterAgent` so critical financial terms (`estorno`, `chargeback`, `fraude`, `balanço`, `faturamento`, `bloqueio`) are never misclassified as `low`.
- Update `_dispatch_next_from_queue` in `src/orchestration/graph.py` to gate low-confidence escalation: low-confidence triggers `escalation_agent` **only** when `risk_tier in ("high", "medium")`.
- Maintain 100% backward compatibility with all 81 existing tests and external contracts.

**Non-Goals:**
- Changing LLM provider or prompting architecture for agents other than `RouterAgent`.
- Modifying how `HumanEscalationAgent` constructs support tickets when it is legitimately invoked.
- Modifying `confidence_escalation_threshold` numeric thresholds (stays at 0.60).

## Decisions

### Decision 1: Extend `RouterPlan` schema in `src/orchestration/state.py`
Add `risk_tier` field:
```python
class RouterPlan(BaseModel):
    routed_agents: list[str] = Field(..., description="Ordered list of agent node names to execute")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Routing confidence score")
    reasoning: str = Field(..., description="Explanation of the routing decision")
    risk_tier: Literal["high", "medium", "low"] = Field(
        default="low",
        description="Business risk classification: high (financial loss/fraud/block), medium (ledger/fees), low (informational/FAQ)"
    )
```
*Rationale:* Defaulting to `"low"` guarantees that any test or mock that instantiates `RouterPlan` without specifying `risk_tier` does not fail validation.

### Decision 2: Update `RouterAgent` prompt and parsing logic in `src/agents/router_agent.py`
Update system prompt with business risk tier rules:
- `high`: Financial loss, active fraud, chargebacks, disputed settlement, blocked hardware/terminals during sales.
- `medium`: Ledger reconciliation, balance/revenue figures, fee disputes, plan change negotiations, contract terms.
- `low`: Informational inquiries, general corporate trivia, product catalog, onboarding FAQs, portal navigation.

Include deterministic safety overrides in the parser:
```python
CRITICAL_FINANCIAL_TOKENS = {"chargeback", "estorno", "fraude", "golpe", "contestação", "bloqueada", "travada"}
LEDGER_TOKENS = {"balanço", "faturamento", "receita", "extrato", "taxa", "tarifa"}

if any(t in message.lower() for t in CRITICAL_FINANCIAL_TOKENS):
    risk_tier = "high"
elif any(t in message.lower() for t in LEDGER_TOKENS) and risk_tier == "low":
    risk_tier = "medium"
```
*Rationale:* Ensures deterministic defense-in-depth against prompt drift or LLM classification flakiness, guaranteeing that financial dispute scenarios (including existing red-teaming tests) are never downgraded to `low`.

### Decision 3: Risk-Tier Gated Escalation in `src/orchestration/graph.py`
Modify `_dispatch_next_from_queue`:
```python
router_plan = state.get("router_plan")
risk_tier = getattr(router_plan, "risk_tier", "low") if router_plan else "low"

if conf < settings.confidence_escalation_threshold and "escalation_agent" not in routed:
    if risk_tier in ("high", "medium"):
        logger.warning(
            "router.escalating_low_confidence",
            confidence=conf,
            threshold=settings.confidence_escalation_threshold,
            risk_tier=risk_tier,
        )
        return "escalation_agent"
    else:
        logger.info(
            "router.escalation_suppressed_low_risk",
            confidence=conf,
            threshold=settings.confidence_escalation_threshold,
            risk_tier=risk_tier,
            reason="Informational/low-risk query with epistemic uncertainty does not require human ticket.",
        )
```
*Rationale:* Low-risk questions with low confidence (e.g. web search fallback with epistemic caveats) return the synthesized informational answer to the user without contaminating the human support queue.

## Risks / Trade-offs

- **[Risk]** Red-teaming test `test_red_teaming_historical_out_of_corpus_triggers_anti_hallucination_and_escalation` checks if query `"Qual o faturamento e balanço exato da Getnet Brasil em 2024?"` triggers escalation.
  → **Mitigation**: This query requests proprietary financial ledger/balance information. By categorizing ledger inquiries under `medium` risk tier, the test query continues to trigger escalation as designed, preserving security and audit expectations.
- **[Risk]** Existing unit test mocks for `RouterPlan` missing `risk_tier`.
  → **Mitigation**: Pydantic field default `default="low"` guarantees that `RouterPlan(routed_agents=[...], confidence=0.9, reasoning="...")` succeeds without error.
