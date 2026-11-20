# Design

## Context

See `proposal.md` for motivation and scope. An audit of the codebase against Getnet's 09/11/2026 review and AI Deployment Engineer production expectations showed:
- `src/api/routes.py` exposes `/chat`, `/chat/stream`, `/chat/history/{user_id}`, `/metrics`, `/alerts`, `/traces`, `/traces/{trace_id}`, `/evals/run`, and `/dashboard` without authentication, RBAC, rate limits, or `ChatRequest.message` `max_length`.
- `src/observability/logger.py`, `src/observability/tracer.py`, and `src/guardrails/validator.py` log raw `message_preview` / span payloads without PCI-DSS sanitization, and `validate_input_message` inspects raw strings without Unicode/base64 normalization.
- `src/orchestration/session_store.py`, `src/tools/support_tools.py` (`_RUNTIME_CREATED_TICKETS`), and `src/orchestration/graph.py` rely solely on volatile in-memory Python dicts without persistent storage or LangGraph checkpointing.
- `scripts/evaluate.py` evaluates answer quality primarily via keyword hit ratios and a basic LLM prompt judge without Ragas RAG metrics or CI threshold gates.
- `Dockerfile` runs as `root` with `tests/` copied into the container, and `docker-compose.yml` mounts `./src:/app/src` under `APP_ENV=production`.

## Goals / Non-Goals

**Goals:**
- Enforce JWT Bearer authentication and RBAC (`merchant`, `operator`, `admin`) across all chat, history, observability, evaluation, dashboard, and HITL endpoints while keeping `/health` and `/favicon.*` public.
- Eliminate IDOR by binding `merchant` callers strictly to their token's `user_id` on `/chat`, `/chat/stream`, `/api/v1/message`, and `/chat/history/{user_id}`.
- Enforce `ChatRequest` `max_length`, per-principal sliding-window rate limits (`429`), and per-request/per-user token budget governance ("anti-token maxxing").
- Apply unified PCI-DSS/LGPD redaction (PANs, CVVs, CPFs/CNPJs, Bearer tokens) across `structlog`, `trace_recorder`, and guardrail previews, plus Unicode/base64 normalization in `validate_input_message`.
- Upgrade `scripts/evaluate.py` and `POST /evals/run` with Ragas metrics (`faithfulness`, `answer_relevancy`, `context_precision`, `context_recall`, `hallucination_rate`), `offline_deterministic` CI mode, threshold enforcement, and `.github/workflows/ci.yml`.
- Back LangGraph HITL (`interrupt()` + `Command(resume=...)`), `SessionStore`, and runtime tickets with SQLite persistence (`data/runtime.db`, configurable to `:memory:` in tests), add `GET /handoffs` and `POST /handoffs/{thread_id}/resume`, and expose an Operator Auth + HITL Queue panel in `DASHBOARD_HTML`.
- Harden `Dockerfile` (non-root user, no `tests/` in image) and `docker-compose.yml` (persistent volumes, no dev `./src` bind mount).

**Non-Goals:**
- External Identity Provider (Okta/Keycloak) or PostgreSQL/Redis cluster deployment; signed HS256 JWTs and SQLite-backed persistence provide self-contained single-container production semantics with clean interfaces for future externalization.
- Separate React SPA build; the interactive dashboard remains served from `src/api/dashboard.py` updated with Bearer token login and HITL review controls.

## Decisions

1. **Authentication, RBAC & Multi-Tenancy (`src/api/auth.py`)**
   - *Choice:* Validate `HS256` JWTs (`PyJWT`) with `sub` (`user_id`), `role` (`merchant` | `operator` | `admin`), and `exp`. Provide `create_access_token()` and a `POST /auth/token` endpoint (enabled via `auth_allow_dev_token_endpoint` or `X-Bootstrap-Key`) so Swagger UI, `/dashboard`, and integration tests can mint tokens cleanly.
   - *Alternatives considered:* Static API keys per role (rejected because they lack per-merchant `sub` isolation for `/chat` and `/chat/history/{user_id}`).

2. **Rate Limiting & Anti-Token-Maxxing Governance (`src/api/rate_limit.py`)**
   - *Choice:* Thread-safe sliding-window rate limiter keyed by `(role, user_id)` returning `429 Too Many Requests` + `Retry-After`, paired with a per-user daily token budget tracker and per-request `max_completion_tokens` ceiling recorded in `settings`. Budget breaches emit a `TOKEN_BUDGET_ALERT` in `trace_recorder` and throttle further LLM calls with `429`.
   - *Alternatives considered:* External Redis rate limiter (rejected to keep Docker self-contained without extra mandatory containers).

3. **Shared PCI-DSS Sanitization & Normalized Ingress Guardrails (`src/guardrails/validator.py`)**
   - *Choice:* Extract `sanitize_sensitive_data()` (masking 13-19 digit PANs, CVV labels, CPFs, CNPJs, and `Bearer ...` headers) and invoke it in `sanitize_output_message()`, a `structlog` processor in `src/observability/logger.py`, and `trace_recorder` in `src/observability/tracer.py`. In `validate_input_message()`, normalize Unicode (`NFKC`, strip zero-width chars) and scan decoded base64 segments before running injection regexes.
   - *Alternatives considered:* Output-only redaction (insufficient because raw PANs/CPFs leak into stdout logs and `/traces`).

4. **Ragas Evaluation Suite & CI Gate (`scripts/evaluate.py`, `.github/workflows/ci.yml`)**
   - *Choice:* Capture `retrieved_contexts` in `execute_orchestration` evaluation hooks / `scripts/evaluate.py`. Use `ragas` metrics (`Faithfulness`, `ResponseRelevancy`, `LLMContextPrecisionWithReference`, `LLMContextRecall`, `hallucination_rate = 1 - faithfulness`) when `OPENAI_API_KEY` is active, and deterministic context-overlap / grounding equivalents (`evaluation_mode="offline_deterministic"`) when offline. Add `--enforce-thresholds` CLI option checked by `.github/workflows/ci.yml` alongside `pytest` and `openspec validate --strict`.
   - *Alternatives considered:* Live-only Ragas (would fail in offline CI without paid API credentials).

5. **Persistent SQLite State + LangGraph `interrupt()` HITL (`src/orchestration/graph.py`, `session_store.py`, `support_tools.py`)**
   - *Choice:* Use `langgraph.checkpoint.sqlite.SqliteSaver` (falling back to `MemorySaver` when `hitl_checkpoint_db_path == ":memory:"` or in isolated unit tests) and persist `SessionStore` turns and runtime support tickets in SQLite (`settings.runtime_db_path`). Inside `_escalation_agent_node`, register the handoff/ticket and call `langgraph.types.interrupt(...)`. Both `execute_orchestration` and `execute_orchestration_stream` invoke the compiled graph with `thread_id`; when `__interrupt__` occurs, they return/emit `handoff_status="pending_human_review"` and `thread_id`. `POST /handoffs/{thread_id}/resume` resumes via `Command(resume=...)` through `personality_agent` and `output_guardrail`, updating `handoff_status="resolved"`.
   - *Alternatives considered:* Keeping `SessionStore` and tickets in RAM (would lose multi-turn context and created tickets across restarts/workers).

6. **Container & CI Hardening (`Dockerfile`, `docker-compose.yml`, `.github/workflows/ci.yml`)**
   - *Choice:* Add non-root `appuser` in `Dockerfile`, omit `tests/` and `.env.example` from the runtime image, remove `./src:/app/src` dev mount from `docker-compose.yml`, and mount persistent `./data/runtime` and `./logs` volumes owned appropriately.
   - *Alternatives considered:* Multi-container reverse proxy (unnecessary complexity when FastAPI enforces auth, rate limits, and non-root execution directly).

## Risks / Trade-offs

- **Existing test suite compatibility with mandatory auth** → Update `tests/conftest.py` with reusable `merchant_headers` and `operator_headers` fixtures, update integration tests to pass tokens, and keep unit tests of pure internal functions unaffected while adding dedicated auth/RBAC/IDOR/rate-limit tests.
- **Ragas / `langgraph-checkpoint-sqlite` dependency compatibility** → Pin compatible versions (`ragas>=0.2.0`, `langgraph-checkpoint-sqlite>=2.0.0`, `PyJWT>=2.9.0`) in `pyproject.toml` and `requirements.txt`, verifying installation inside `.venv` before running tests.
- **SQLite file locking across tests** → Use `":memory:"` or `tmp_path` fixtures in `pytest` so tests stay isolated and fast while production defaults to `data/runtime/getnet_runtime.db`.
