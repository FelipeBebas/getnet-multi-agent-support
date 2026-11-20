# Tasks

## 1. Dependencies & Configuration

- [x] 1.1 Add `PyJWT>=2.9.0`, `ragas>=0.2.0`, `datasets>=3.0.0`, and `langgraph-checkpoint-sqlite>=2.0.0` to `pyproject.toml` and `requirements.txt`, install them in `.venv`, and verify all imports resolve cleanly.
- [x] 1.2 Add auth/JWT, rate-limit, token-budget, Ragas CI threshold, and SQLite persistence settings (`auth_jwt_secret`, `auth_jwt_algorithm`, `auth_token_ttl_seconds`, `auth_allow_dev_token_endpoint`, `auth_bootstrap_api_key`, `rate_limit_requests_per_minute`, `daily_token_budget_per_user`, `max_message_length`, `runtime_db_path`, `hitl_checkpoint_db_path`, `eval_min_faithfulness`, `eval_max_hallucination_rate`) to `src/config/settings.py` and `.env.example`, verifying `Settings()` instantiates cleanly.

## 2. Authentication, RBAC, Rate Limits & PCI-DSS Sanitization

- [x] 2.1 Implement `src/api/auth.py` (`Principal`, `create_access_token()`, `get_current_principal()`, `require_roles()`, `assert_user_access()`, and optional `POST /auth/token` helper) and verify unit tests cover valid tokens, invalid/expired tokens (`401`), role denials (`403`), and cross-tenant IDOR denials (`403`).
- [x] 2.2 Implement `src/api/rate_limit.py` (sliding-window rate limiter + per-user token budget tracker) and enforce `max_length` on `ChatRequest` in `src/api/schemas.py`, verifying unit tests cover `422` oversized payloads and `429` rate/budget throttling with `Retry-After`.
- [x] 2.3 Implement unified `sanitize_sensitive_data()` (PAN, CVV, CPF, CNPJ, Bearer tokens) and Unicode/base64 normalization in `src/guardrails/validator.py`, wire sanitization into `src/observability/logger.py` and `src/observability/tracer.py`, and verify unit tests in `tests/unit/test_guardrails.py` and `tests/unit/test_observability.py` confirm obfuscated injections are blocked and logs/traces mask all PII.
- [x] 2.4 Protect `/chat`, `/chat/stream`, `/api/v1/message`, `/chat/history/{user_id}`, `/traces`, `/traces/{trace_id}`, `/alerts`, `/metrics`, `/evals/run`, and `/dashboard` in `src/api/routes.py` with RBAC, tenant isolation, and rate/budget guards, update `tests/conftest.py` and `tests/integration/test_api_endpoints.py`, and verify `pytest` covers `200`, `401`, `403`, `422`, and `429`.

## 3. Quantitative Ragas Evaluation Suite & CI Quality Gate

- [x] 3.1 Capture `retrieved_contexts` in orchestration trace/eval outputs (`src/orchestration/graph.py` / `scripts/evaluate.py`) and enrich `data/eval_dataset.json` with reference contexts where applicable, verifying scenario runs preserve retrieved chunks.
- [x] 3.2 Upgrade `scripts/evaluate.py` to compute Ragas metrics (`faithfulness`, `answer_relevancy`, `context_precision`, `context_recall`, `hallucination_rate`) in live LLM mode and `offline_deterministic` mode without an API key, plus `--enforce-thresholds` CLI exit codes, and verify `python scripts/evaluate.py --enforce-thresholds` exits `0`.
- [x] 3.3 Add unit and integration tests for `scripts/evaluate.py` and `POST /evals/run` asserting metric keys, `[0.0, 1.0]` bounds, `hallucination_rate == round(1.0 - faithfulness, 4)`, and threshold failure behavior, and verify `pytest` passes.

## 4. Persistent State & Real LangGraph HITL (`interrupt()`)

- [x] 4.1 Add SQLite persistence (with `:memory:` test mode) to `src/orchestration/session_store.py` and `src/tools/support_tools.py` (`_RUNTIME_CREATED_TICKETS` replacement), and verify `tests/unit/test_session_memory.py` and `tests/unit/test_tools.py` pass across store reloads.
- [x] 4.2 Add `thread_id`, `handoff_status`, and `human_decision` to `OrchestrationState` (`src/orchestration/state.py`) and `ChatResponse` (`src/api/schemas.py`), plus `HandoffResumeRequest` and `HandoffSummary` schemas, and verify schema tests pass.
- [x] 4.3 Wire `SqliteSaver`/`MemorySaver` checkpointer into `build_orchestration_graph()`, update `_escalation_agent_node` (`src/orchestration/graph.py`) and `src/agents/escalation_agent.py` to suspend via `langgraph.types.interrupt()` (while keeping `low` risk-tier low-confidence queries non-escalating), and verify `tests/unit/test_orchestrator.py` confirms pause and `Command(resume=...)` continuation.
- [x] 4.4 Implement operator-authenticated `GET /handoffs` and `POST /handoffs/{thread_id}/resume` (returning `404`/`409` for invalid/non-paused threads), update `execute_orchestration_stream` to emit `interrupt` SSE events, and add an Operator Auth + Pending HITL Queue panel to `src/api/dashboard.py`, verifying end-to-end pause/resume integration tests pass.

## 5. Container, CI/CD & Documentation Hardening

- [x] 5.1 Harden `Dockerfile` (non-root `appuser`, exclude `tests/` and `.env.example`) and `docker-compose.yml` (remove dev `./src` bind mount, mount persistent runtime/logs volumes), verifying `docker build` / compose config validation succeeds.
- [x] 5.2 Add `.github/workflows/ci.yml` running `pytest`, `python scripts/evaluate.py --enforce-thresholds`, and `openspec validate --strict`, and verify all local equivalents pass with exit code `0`.
- [x] 5.3 Update `README.md` with JWT/RBAC auth instructions, rate-limit/token-budget governance, Ragas evaluation scorecard metrics, HITL `interrupt()` / `/handoffs/{thread_id}/resume` workflow, and guardrail trade-offs, and run the full `pytest` suite and `openspec validate getnet-feedback-hardening --strict` to confirm everything passes.

## Workflow follow-up

- Run `/opsx-apply` (or ask to apply `getnet-feedback-hardening`) to implement all tasks above.
- Archive `getnet-feedback-hardening` and `authentic-rag-langsmith-and-tree-dashboard` after verification.
