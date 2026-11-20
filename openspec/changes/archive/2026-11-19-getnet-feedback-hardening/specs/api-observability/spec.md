# Spec Delta

## MODIFIED Requirements

### Requirement: Containerized Service Packaging
The system SHALL build and run as a hardened, non-root containerized service using standard Docker commands (`docker build`, `docker run`, or `docker compose up`) with healthcheck verification and persistent runtime volume support, excluding test suites from the production image.

#### Scenario: Container startup and health probe
- **WHEN** the service is started via Docker as a non-root user and a client sends `GET /health`
- **THEN** the service responds with HTTP `200 OK` indicating API readiness and vector store availability

### Requirement: Structured Logging, LangSmith Tracing, Alerting, and Visual Dashboard
The system SHALL emit structured JSON logs with sensitive-data masking, record an execution trace for every request (compatible with LangSmith `LANGCHAIN_TRACING_V2` and access-controlled local `/traces` inspection), evaluate operational/security alerting rules (`GET /alerts`), and serve an interactive visual architecture & observability dashboard (`GET /dashboard`) gated to authorized `operator` or `admin` roles.

#### Scenario: Trace recorded across multi-agent execution
- **WHEN** a request traverses the Router Agent, a specialized agent, and the Personality Agent
- **THEN** the system logs sanitized structured events correlated by `trace_id` and exports trace spans to LangSmith (when configured) and the local trace store (`GET /traces/{trace_id}`)

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
