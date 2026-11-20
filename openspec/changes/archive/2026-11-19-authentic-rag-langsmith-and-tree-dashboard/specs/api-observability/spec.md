# Spec Delta

## MODIFIED Requirements

### Requirement: Structured Logging, LangSmith Tracing, Alerting, and Visual Dashboard
The system SHALL emit structured JSON logs, record an execution trace for every request (compatible with LangSmith `LANGCHAIN_TRACING_V2` and local `/traces` inspection), evaluate operational/security alerting rules (`GET /alerts`), and serve an interactive visual architecture & observability dashboard (`GET /dashboard`) displaying the multi-agent orchestration as a hierarchical tree (DAG) rather than a flat horizontal queue.

#### Scenario: Trace recorded across multi-agent execution
- **WHEN** a request traverses the Input Guardrail, Router Agent, a specialized agent and its tools, the Personality Agent, and the Output Guardrail
- **THEN** the system logs structured events correlated by `trace_id`, exports trace spans and token/latency metrics to LangSmith (when configured) and the local trace store (`GET /traces/{trace_id}`), and highlights the active tree branches and child tool nodes in `GET /dashboard`

#### Scenario: Production alerting triggered on SLO breach or security block
- **WHEN** a request exceeds latency thresholds, triggers a guardrail prompt-injection block, or requires human escalation
- **THEN** the alerting engine records a structured alert accessible via `GET /alerts` and `GET /metrics`

### Requirement: Automated Scenario Evaluation Suite
The system SHALL provide an automated evaluation runner (`scripts/evaluate.py` and `POST /evals/run`) that executes the 10 reference test scenarios from the challenge specification plus bonus cases both locally and via `langsmith.evaluation.evaluate`, computing and publishing routing accuracy, tool selection accuracy, rubric groundedness, and LLM faithfulness scores directly to LangSmith.

#### Scenario: Running the evaluation benchmark
- **WHEN** a developer or CI pipeline runs `python scripts/evaluate.py --sync-langsmith` (or calls `POST /evals/run`) against the 10 reference scenarios for `cliente1988`
- **THEN** the runner syncs the dataset to LangSmith, runs a formal LangSmith Experiment with custom evaluators (`routing_accuracy`, `tool_accuracy`, `rubric_groundedness`, `llm_faithfulness`), and outputs a structured evaluation report verifying that each scenario routed to the expected agent, invoked the expected tool, and produced a grounded answer
