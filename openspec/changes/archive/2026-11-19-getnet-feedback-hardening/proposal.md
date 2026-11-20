# Proposal

## Why

During Getnet's technical evaluation (09/11/2026) of the `getnet-multi-agent` system, the engineering panel validated the LangGraph orchestration, hybrid RAG grounding, and observability instrumentation, but identified three production-readiness gaps required for a regulated fintech/PCI-DSS environment: unauthenticated sensitive endpoints, keyword-based evaluation metrics instead of quantitative RAG evaluation frameworks, and static ticket escalation without real Human-in-the-Loop (HITL) graph suspension and resumption. A deep audit of the codebase against the AI Deployment Engineer role expectations also revealed implicit production gaps—IDOR on `POST /chat`, missing input size/rate limits and token-budget ("anti-token maxxing") controls, volatile RAM-only state, prompt-injection encoding bypass vectors, and root-privileged Docker packaging—that should be closed together for a complete banking-grade architecture.

## What Changes

- **Authentication, RBAC & PCI-DSS Telemetry Isolation:** Introduce Bearer JWT authentication and Role-Based Access Control (`merchant` vs. `operator`/`admin`) across `/chat`, `/chat/stream`, `/api/v1/message`, `/chat/history/{user_id}`, `/traces`, `/traces/{trace_id}`, `/alerts`, `/metrics`, `/evals/run`, `/dashboard`, and HITL endpoints; enforce strict `user_id` tenant isolation to prevent IDOR; and sanitize PANs, CVVs, CPFs/CNPJs, and credentials in structured logs, guardrail previews, and trace records.
- **Anti-Token Maxxing, Rate Limiting & Guardrail Hardening:** Enforce `max_length` bounds on `ChatRequest`, per-caller sliding-window rate limiting (`429 Too Many Requests`), per-request/per-user token budget tracking and caps, and Unicode/base64 normalization in `validate_input_message` to resist encoding-based prompt-injection bypasses.
- **Quantitative Evals Suite (Ragas) & CI Quality Gate:** Upgrade `scripts/evaluate.py` and `POST /evals/run` from keyword-matching heuristics to quantitative RAG/generation evaluation metrics (`faithfulness`, `answer_relevancy`, `context_precision`, `context_recall`, and `hallucination_rate`) using Ragas with an offline/deterministic fallback (`offline_deterministic`), configurable CI threshold enforcement, and a GitHub Actions CI workflow (`.github/workflows/ci.yml`).
- **Real Human-in-the-Loop (HITL) with LangGraph `interrupt()` & Persistence:** Configure SQLite-backed persistence (with in-memory test support) for LangGraph checkpoints (`SqliteSaver`/`MemorySaver`), conversational session memory, and runtime support tickets; update `escalation_agent` and `src/orchestration/graph.py` to suspend via `interrupt()` and resume via `Command(resume=...)` through `GET /handoffs`, `POST /handoffs/{thread_id}/resume`, and an operator review panel in `/dashboard`.
- **Container Production Hardening:** Update `Dockerfile` to run as a non-root user excluding test artifacts from the runtime image, and clean `docker-compose.yml` by removing development source bind mounts and mounting persistent data/log volumes.

## Capabilities

### New Capabilities
- `api-security-rbac`: Token-based authentication, role-based access control (`merchant`, `operator`, `admin`), per-`user_id` tenant isolation on chat and history routes, PCI-DSS sanitization of logs and traces, and API rate-limiting and token-budget enforcement.

### Modified Capabilities
- `api-observability`: Protect observability, trace, alert, metric, and evaluation endpoints with RBAC; extend the Automated Scenario Evaluation Suite with quantitative Ragas metrics and CI threshold enforcement; and harden containerized runtime packaging and persistence.
- `guardrails-escalation`: Harden input prompt-injection detection against encoding/normalization bypasses, and upgrade the Human Escalation and Handoff Agent to suspend/resume execution via persistent LangGraph `interrupt()` checkpoints and operator endpoints.

## Impact

- **API, Auth & Rate Limiting:** `src/api/auth.py` (new), `src/api/rate_limit.py` (new), `src/api/routes.py`, `src/api/schemas.py`, `src/api/dashboard.py`, `src/config/settings.py`
- **Guardrails & Orchestration:** `src/guardrails/validator.py`, `src/orchestration/state.py`, `src/orchestration/graph.py`, `src/orchestration/session_store.py`, `src/agents/escalation_agent.py`, `src/tools/support_tools.py`
- **Observability & Sanitization:** `src/observability/logger.py`, `src/observability/tracer.py`
- **Evals, CI & Container:** `scripts/evaluate.py`, `pyproject.toml`, `requirements.txt`, `Dockerfile`, `docker-compose.yml`, `.github/workflows/ci.yml` (new)
- **Tests & Documentation:** `tests/unit/`, `tests/integration/`, `README.md`
