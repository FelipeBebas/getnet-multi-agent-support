# api-observability Specification

## Purpose

Exposes the multi-agent orchestration over a containerized HTTP API and provides structured logging, end-to-end execution tracing, operational metrics, and automated scenario evaluation.

## Requirements

### Requirement: HTTP POST Message Endpoint Contract
The system SHALL expose an HTTP `POST` endpoint that accepts a JSON payload containing `message` and `user_id` and returns a structured JSON response with the synthesized answer and orchestration metadata.

#### Scenario: Valid POST request processed by orchestration
- **WHEN** a client sends a `POST` request with `{"message": "Can I sell through WhatsApp using the Payment Link?", "user_id": "cliente1988"}`
- **THEN** the API returns HTTP `200 OK` with a JSON object containing `response`, `user_id`, `routed_agents`, `tools_used`, `sources`, `handoff_required`, and `trace_id`

#### Scenario: Malformed payload rejected with validation error
- **WHEN** a client sends a `POST` request missing `message` or `user_id` or with an empty message string
- **THEN** the API returns HTTP `422 Unprocessable Entity` detailing the schema validation failure

### Requirement: Containerized Service Packaging
The system SHALL build and run as a hardened, non-root containerized service using standard Docker commands (`docker build`, `docker run`, or `docker compose up`) with healthcheck verification and persistent runtime volume support, excluding test suites from the production image.

#### Scenario: Container startup and health probe
- **WHEN** the service is started via Docker as a non-root user and a client sends `GET /health`
- **THEN** the service responds with HTTP `200 OK` indicating API readiness and vector store availability

### Requirement: Structured Logging, LangSmith Tracing, Alerting, and Visual Dashboard
The system SHALL emit structured JSON logs with sensitive-data masking, record an execution trace for every request (compatible with LangSmith `LANGCHAIN_TRACING_V2` and access-controlled local `/traces` inspection), evaluate operational/security alerting rules (`GET /alerts`), and serve an interactive visual architecture & observability dashboard (`GET /dashboard`) gated to authorized `operator` or `admin` roles displaying the multi-agent orchestration as a hierarchical tree (DAG).

#### Scenario: Trace recorded across multi-agent execution
- **WHEN** a request traverses the Input Guardrail, Router Agent, a specialized agent and its tools, the Personality Agent, and the Output Guardrail
- **THEN** the system logs sanitized structured events correlated by `trace_id`, exports trace spans and token/latency metrics to LangSmith (when configured) and the local trace store (`GET /traces/{trace_id}`), and highlights active tree branches and child tool nodes in `GET /dashboard`

#### Scenario: Production alerting triggered on SLO breach or security block
- **WHEN** a request exceeds latency thresholds, triggers a guardrail prompt-injection block, or requires human escalation
- **THEN** the alerting engine records a structured alert accessible via `GET /alerts` and `GET /metrics` for authenticated `operator` or `admin` callers

### Requirement: Automated Scenario Evaluation Suite
The system SHALL provide an automated evaluation runner (`scripts/evaluate.py` and `POST /evals/run`) that executes the reference test scenarios and computes routing accuracy, tool selection accuracy, and quantitative RAG/generation quality metrics (`faithfulness`, `answer_relevancy`, `context_precision`, `context_recall`, and `hallucination_rate`) using Ragas with a deterministic offline fallback and optional CI threshold enforcement.

#### Scenario: Running the evaluation benchmark
- **WHEN** an authorized operator or CI pipeline runs the evaluation suite against the reference scenarios for `cliente1988`
- **THEN** the runner outputs a structured evaluation scorecard verifying routing accuracy, tool selection accuracy, grounded answers, and quantitative Ragas metrics (`faithfulness`, `answer_relevancy`, `context_precision`, `context_recall`, and `hallucination_rate`)

#### Scenario: Offline CI evaluation without external LLM API key
- **WHEN** the evaluation suite runs in offline/mock mode without a live `OPENAI_API_KEY`
- **THEN** the runner completes deterministically without external network failures and reports grounded quantitative Ragas-compatible metric scores plus `evaluation_mode="offline_deterministic"`

#### Scenario: CI quality gate fails on regression below thresholds
- **WHEN** the evaluation CLI runs with threshold enforcement and aggregate `faithfulness` falls below or `hallucination_rate` exceeds the configured threshold
- **THEN** the CLI exits with a non-zero exit code reporting the violated quality gates
