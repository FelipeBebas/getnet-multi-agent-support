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
The system SHALL build and run as a self-contained containerized service using standard Docker commands (`docker build`, `docker run`, or `docker compose up`) with healthcheck verification.

#### Scenario: Container startup and health probe
- **WHEN** the service is started via Docker and a client sends `GET /health`
- **THEN** the service responds with HTTP `200 OK` indicating API readiness and vector store availability

### Requirement: Structured Logging, LangSmith Tracing, Alerting, and Visual Dashboard
The system SHALL emit structured JSON logs, record an execution trace for every request (compatible with LangSmith `LANGCHAIN_TRACING_V2` and local `/traces` inspection), evaluate operational/security alerting rules (`GET /alerts`), and serve an interactive visual architecture & observability dashboard (`GET /dashboard`).

#### Scenario: Trace recorded across multi-agent execution
- **WHEN** a request traverses the Router Agent, a specialized agent, and the Personality Agent
- **THEN** the system logs structured events correlated by `trace_id` and exports trace spans to LangSmith (when configured) and the local trace store (`GET /traces/{trace_id}`)

#### Scenario: Production alerting triggered on SLO breach or security block
- **WHEN** a request exceeds latency thresholds, triggers a guardrail prompt-injection block, or requires human escalation
- **THEN** the alerting engine records a structured alert accessible via `GET /alerts` and `GET /metrics`

### Requirement: Automated Scenario Evaluation Suite
The system SHALL provide an automated evaluation runner that executes the 10 reference test scenarios from the challenge specification and computes routing accuracy, tool selection accuracy, and answer quality scores.

#### Scenario: Running the evaluation benchmark
- **WHEN** a developer or CI pipeline runs the evaluation suite against the 10 reference scenarios for `cliente1988`
- **THEN** the runner outputs a structured evaluation report verifying that each scenario routed to the expected agent, invoked the expected tool, and produced a grounded answer
