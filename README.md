# Getnet Multi-Agent Support System

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-StateGraph%20%2B%20HITL-orange.svg)](https://langchain-ai.github.io/langgraph/)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-Vector_Store-green.svg)](https://www.trychroma.com/)
[![Ragas Evals](https://img.shields.io/badge/Ragas-Evals%20%2B%20CI%20Gate-blueviolet.svg)](scripts/evaluate.py)
[![OpenSpec](https://img.shields.io/badge/Spec--Driven-OpenSpec-purple.svg)](openspec/specs/)
[![Tests Passing](https://img.shields.io/badge/Tests-117%2F117%20PASS-brightgreen.svg)](tests/)
[![Challenge Benchmark](https://img.shields.io/badge/Challenge%20Scenarios-10%2F10%20(100%25)-success.svg)](scripts/evaluate.py)

Fintech production-hardened, **Spec-Driven Multi-Agent Support System** engineered for Getnet acquiring & merchant operations. Built with **Python 3.12**, **FastAPI**, **LangGraph** (`interrupt()` + `SqliteSaver`), **ChromaDB**, **Ragas**, **LangSmith**, and **OpenSpec**.

---

## Production Hardening Highlights (v2 Architecture)

| Banking / Production Requirement | Implemented Engineering Control | Primary Modules |
| :--- | :--- | :--- |
| **Access Control & Anti-IDOR (PCI-DSS)** | Signed `HS256` Bearer JWTs + `HttpOnly` browser session cookies, RBAC (`merchant` vs. `operator`/`admin`), strict per-`user_id` tenant isolation | [`src/api/auth.py`](src/api/auth.py), [`src/api/routes.py`](src/api/routes.py) |
| **Telemetry & Log Redaction (PCI / LGPD)** | Unified masking of 13–19 digit PANs, CVVs, CPFs, CNPJs, and Bearer/API tokens across egress responses, `structlog` JSON logs, and `/traces` | [`src/guardrails/redaction.py`](src/guardrails/redaction.py), [`src/observability/logger.py`](src/observability/logger.py), [`src/observability/tracer.py`](src/observability/tracer.py) |
| **Anti-Token Maxxing & Abuse Prevention** | Bounded `ChatRequest.message` length (`422`), sliding-window rate limits (`429` + `Retry-After`), daily & per-request token budget caps + alerts | [`src/api/rate_limit.py`](src/api/rate_limit.py), [`src/api/schemas.py`](src/api/schemas.py) |
| **Obfuscation-Resistant Guardrails** | Unicode `NFKC` + homoglyph/zero-width normalization and base64 payload inspection before prompt-injection and fraud regex checks | [`src/guardrails/validator.py`](src/guardrails/validator.py) |
| **Quantitative RAG Evaluation & CI Gate** | **Ragas** metrics (`faithfulness`, `answer_relevancy`, `context_precision`, `context_recall`, `hallucination_rate`) with offline deterministic CI fallback and `--enforce-thresholds` | [`scripts/evaluate.py`](scripts/evaluate.py), [`.github/workflows/ci.yml`](.github/workflows/ci.yml) |
| **Real Human-in-the-Loop (HITL) & Persistence** | LangGraph `interrupt()` suspension + `Command(resume=...)` over `SqliteSaver`, SQLite-backed session history, runtime CRM tickets, and `/dashboard` HITL Review Queue | [`src/orchestration/graph.py`](src/orchestration/graph.py), [`src/orchestration/persistence.py`](src/orchestration/persistence.py) |
| **Container Security** | Non-root `appuser` execution, test/dev files excluded from image, `no-new-privileges`, and persistent runtime/log volumes | [`Dockerfile`](Dockerfile), [`docker-compose.yml`](docker-compose.yml) |

---

## Video Presentation & Walkthrough (v1 Baseline)

[![Getnet Multi-Agent Solution Walkthrough](docs/assets/video-thumbnail.png)](https://drive.google.com/file/d/1MhL4jDibYF79vLd7Dm_1SuRnT12zpLuW/view?usp=sharing)

<p align="center">
  <em><b><a href="https://drive.google.com/file/d/1MhL4jDibYF79vLd7Dm_1SuRnT12zpLuW/view?usp=sharing" target="_blank" rel="noopener noreferrer">Watch the v1 Architecture Walkthrough (13 min) on Google Drive</a></b></em>
</p>

> **Note:** The video above walks through the **v1** core 5-agent LangGraph design, hybrid ChromaDB RAG, and visual execution tree. Following technical review, the repository was upgraded to **v2** with JWT/RBAC, PCI-DSS telemetry sanitization, Ragas Evals + CI gate, SQLite persistence, and real LangGraph `interrupt()` HITL resumption.

---

## 1. Architecture Overview & Multi-Agent Workflow

The system implements a deterministic, fully observable **5-Agent LangGraph (`StateGraph`) Orchestration** behind an authenticated FastAPI gateway and bidirectional security guardrails:

```mermaid
flowchart TD
    User(["Client / Browser\nBearer JWT or HttpOnly Cookie"]) --> Gateway["API Security Gateway\n(RBAC, Tenant Isolation, Rate Limit & Token Budget)"]
    Gateway -- "401 / 403 / 429" --> Reject(["HTTP Error + Operational Alert"])
    Gateway -- "Authorized" --> InGuard["Input Guardrail\n(NFKC + Base64 Decode + Injection Defense)"]

    InGuard -- "Blocked" --> OutGuard["Output Guardrail\n(PCI-DSS PAN/CVV & LGPD CPF/CNPJ Redaction)"]
    InGuard -- "Allowed" --> Router["Agent 1: Router Agent\n(Query Rewriter, Intent & 3-Tier Risk Classification)"]

    Router -- "knowledge" --> Knowledge["Agent 2: Knowledge Agent\n(3-Layer RAG & Scoped Web Search)"]
    Router -- "customer_support" --> Support["Agent 3: Customer Support Agent\n(Merchant Settlements, POS & Tickets)"]
    Router -- "escalation" --> Escalation["Agent 4: Human Escalation Agent\n(LangGraph interrupt + SqliteSaver)"]
    Router -- "hybrid" --> Knowledge

    Knowledge <--> KTools[("Knowledge Tools:\n1. retrieve_getnet_knowledge\n2. web_search_general")]
    Support <--> STools[("Support Tools:\n1. get_merchant_settlement_status\n2. diagnose_pos_and_transactions\n3. manage_support_ticket")]
    Escalation <--> ETools[("Escalation Tools:\n1. dispatch_human_handoff\n2. manage_support_ticket")]

    Knowledge --> QueueGate{"Next queued agent\nor Low Conf & Risk?"}
    Support --> QueueGate

    QueueGate -- "Next: customer_support" --> Support
    QueueGate -- "Low Conf & High/Medium Risk" --> Escalation
    QueueGate -- "Complete / Low Risk" --> Personality["Agent 5: Personality Agent\n(Synthesis, Empathy & SSE Streaming)"]

    Escalation -- "Paused: interrupt()" --> Checkpoint[("Pending HITL Queue\nGET /handoffs")]
    Checkpoint -- "POST /handoffs/{thread_id}/resume\nCommand(resume=...)" --> Personality

    Personality --> OutGuard
    OutGuard --> Final(["JSON / SSE Response\n+ Sanitized Trace & Persisted Session"])
```

### Agent Roles & Responsibilities

1. **Agent 1 — Router Agent (`src/agents/router_agent.py`)**:
   - Primary gateway for validated requests, operating a **Contextual Query Rewriter** (`rewrite_contextual_query`) for elliptical multi-turn follow-ups (e.g., *"what about yen?"*, *"quanto custa ela?"*).
   - Emits a structured `RouterPlan` classifying intent (`knowledge`, `customer_support`, `escalation`, `hybrid`, `out_of_scope`), ordered `agent_queue`, language (`en`/`pt`), and **3-tier business risk** (`high`, `medium`, `low`) so low-risk informational queries never trigger unnecessary human tickets.
2. **Agent 2 — Knowledge Agent (`src/agents/knowledge_agent.py`)**:
   - Answers Getnet product, hardware, and policy questions via **3-Layer RAG** grounded in `https://www.getnet.net/en` and `https://site.getnet.com.br`.
   - Handles real-time external queries (Porto Alegre weather, currency FX) via `web_search_general` and enforces an **Anti-Hallucination & Epistemic Uncertainty Gate** (`[INSUFFICIENT_EVIDENCE]`).
3. **Agent 3 — Customer Support Agent (`src/agents/support_agent.py`)**:
   - Resolves merchant-specific inquiries strictly scoped to the authenticated `user_id` (`cliente1988`) using **3 domain tools**: settlement lookup, POS/ISO-8583 diagnostics, and SQLite-backed ticket management.
4. **Agent 4 (Bonus) — Human Escalation & HITL Agent (`src/agents/escalation_agent.py`)**:
   - Triggered on explicit human requests, contested chargebacks, or confidence `< 0.60` under `high`/`medium` business risk.
   - Dispatches handoff protocols (`ESC-GN-XXXXXX`), creates persistent tickets (`TCK-2026-XXXXXX`), and **suspends graph execution via LangGraph `interrupt()`** under `thread_id` (`SqliteSaver` checkpoint). Resumes via `Command(resume=...)` when an operator submits a decision on `POST /handoffs/{thread_id}/resume`.
5. **Agent 5 — Personality & Output Synthesis Agent (`src/agents/personality_agent.py`)**:
   - Synthesizes specialist findings and operator resolutions into empathetic, brand-aligned responses in the merchant's language (`en` or `pt`), supporting SSE streaming via `POST /chat/stream`.

---

## 2. How LLM Tools Are Engineered

1. **Typed Pydantic Contracts & Deterministic Fallbacks:** Every tool in `src/tools/` is a pure, typed Python function wrapped with `@tool` so unit tests and offline CI run deterministically without external LLM flakes.
2. **Tool Inventory:**
   - `retrieve_getnet_knowledge(query, top_k)`: Queries ChromaDB with hybrid domain-concept + n-gram similarity.
   - `web_search_general(query)`: Multi-provider search (Open-Meteo with local timezone resolution, Frankfurter ECB, AwesomeAPI, DuckDuckGo, Tavily, Wikipedia) filtered through an *Attributed Citations Gate*.
   - `get_merchant_settlement_status(user_id)`: Retrieves gross/net sales, `D+1`/`D+2` deposit windows, and masked bank accounts.
   - `diagnose_pos_and_transactions(user_id, issue_type)`: Inspects terminal hardware, Wi-Fi 2.4GHz/4G APN telemetry, and ISO-8583 decline codes (e.g., Code 51).
   - `manage_support_ticket(user_id, issue_summary, action)`: Persists and queries technical assistance tickets in SQLite.
   - `dispatch_human_handoff(user_id, reason, conversation_summary, priority)`: Generates priority Tier-2 escalation protocols linked to HITL checkpoints.

---

## 3. RAG Pipeline (`Ingestion → Storage → Retrieval → Generation`)

```mermaid
flowchart LR
    A["Layer 1: Ingestion\n(Live Scraper + Curated Corpus)"] --> B["Layer 2: Storage\n(ChromaDB + Hybrid Embeddings)"]
    B --> C["Layer 3: Retrieval\n(Top-k Cosine + Concept Rerank)"]
    C --> D["Layer 4: Grounded Generation\n(Anti-Hallucination & Citations)"]
    C -. "Similarity < 0.35" .-> E["Dynamic Fallback\n(Live Scoped Domain Search)"]
    E --> D
```

1. **Ingestion (`src/rag/ingest.py`, `scripts/ingest_kb.py`):** Live scraping (`httpx` + `BeautifulSoup4`) of Getnet URLs plus curated corpus (`data/knowledge_base/getnet_products.md`) covering *Get Tap*, *Get Mini*, *Get Lite*, *Get Clássica*, *Get Smart*, *Pix*, *Antecipação*, *Crediário* (up to 48x, D+2), and *Payment Link (GetPay)* (`chunk_size=1450`, `chunk_overlap=180`).
2. **Storage (`src/rag/vector_store.py`):** Persistent ChromaDB (`data/chroma_db`) with `GetnetHybridEmbeddingFunction` (128-dim bilingual domain + n-gram embeddings) and optional `OpenAIEmbeddings`.
3. **Retrieval & Fallback (`src/tools/knowledge_tools.py`):** Top-$k$ ($k=4$) retrieval with corrective domain-scoped live search fallback when similarity `< 0.35`.
4. **Grounded Generation (`src/agents/knowledge_agent.py`):** Direct entailment rules prevent fabrication of unlisted products or unverified facts, attaching verified source URLs and `retrieved_contexts` for Ragas scoring.

---

## 4. Spec-Driven Development Lifecycle (OpenSpec)

All capabilities and production hardenings are governed by formal specs under [`openspec/specs/`](openspec/specs/) and archived changes under [`openspec/changes/archive/`](openspec/changes/archive/):

1. **Phase 1 — Core Solution:** 3 core agents, `POST /chat`, ChromaDB RAG, and Docker packaging (`2026-10-25-multi-agent-support-system`).
2. **Phase 2 — Risk-Tier Escalation, Authentic RAG & Tree Dashboard:** 3-tier business risk gating (`2026-10-29-escalation-gating-by-risk-tier`), LangSmith experiments, and hierarchical DAG dashboard (`2026-11-19-authentic-rag-langsmith-and-tree-dashboard`).
3. **Phase 3 — Fintech Production Hardening (`2026-11-19-getnet-feedback-hardening`):** JWT/RBAC & anti-IDOR (`api-security-rbac`), PCI-DSS log/trace redaction, rate/token-budget governance, Ragas evaluation + CI gate, real LangGraph `interrupt()` HITL + SQLite persistence, and non-root Docker hardening.

---

## 5. How to Build, Configure, and Run

### Option A: Docker Compose (Recommended for Production)

```bash
# 1. Copy .env.example to .env and configure AUTH_JWT_SECRET, AUTH_BOOTSTRAP_API_KEY, and optional OPENAI_API_KEY
cp .env.example .env

# 2. Build and start the hardened non-root container with persistent ./data/runtime and ./logs volumes
docker compose up --build -d

# 3. Verify container health
curl http://localhost:8000/health
```

### Option B: Standard Docker Build (Non-Root Verification)

```bash
docker build -t getnet-multi-agent-support .
docker run --rm getnet-multi-agent-support id   # verifies non-root uid/gid (appuser)
docker run --rm -p 8000:8000 --env-file .env.example getnet-multi-agent-support
```

### Option C: Local Python 3.12 (`uv` / `.venv`)

```powershell
# 1. Create virtual environment and install dependencies
uv venv --python 3.12 .venv
uv pip install --python .\.venv\Scripts\python.exe -r requirements.txt

# 2. Seed/verify the ChromaDB knowledge base
.\.venv\Scripts\python.exe scripts/ingest_kb.py --skip-live-scrape

# 3. Start the FastAPI application
.\.venv\Scripts\python.exe -m uvicorn src.main:app --host 127.0.0.1 --port 8000
```

> **Opening `/dashboard` in a Browser:** Navigate to `http://127.0.0.1:8000/dashboard`. Unauthenticated browser requests receive a `401` sign-in console; enter **Bootstrap Key** `getnet-bootstrap-operator-key` (or the value in your `.env`) to establish an `HttpOnly` operator session cookie.

---

## 6. API Endpoints, Security (JWT/RBAC) & Contract

| Method | Endpoint | Access / Role | Description |
| :--- | :--- | :--- | :--- |
| `POST` | `/auth/token` | Public (dev `merchant`) / `X-Bootstrap-Key` (elevated/prod) | Issue a signed `HS256` Bearer JWT (`merchant`, `operator`, `admin`) |
| `POST` | `/auth/session` / `/auth/logout` | Bootstrap key or Operator JWT / Public | Create or clear an `HttpOnly` cookie session for browser ops UI |
| `POST` | `/chat` (aliases: `/`, `/api/v1/message`) | Authenticated (`merchant` own `user_id` / `operator`) | Multi-agent orchestration (`max_length`, rate-limit & token-budget guarded) |
| `POST` | `/chat/stream` | Authenticated (`merchant` own `user_id` / `operator`) | SSE streaming node lifecycle, token chunks, and `interrupt` HITL events |
| `GET` / `DELETE` | `/chat/history/{user_id}` | Authenticated (`merchant` own `user_id` / `operator`) | Retrieve or clear SQLite-persisted conversational history |
| `GET` | `/handoffs` | `operator` / `admin` | List pending (`pending_human_review`) and resolved HITL checkpoints |
| `POST` | `/handoffs/{thread_id}/resume` | `operator` / `admin` | Resume a paused LangGraph `interrupt()` checkpoint via `Command(resume=...)` |
| `GET` | `/dashboard` (also `/`) | `operator` / `admin` (cookie or Bearer) | Interactive Visual Explainer, Live Observability & HITL Review Queue UI |
| `GET` | `/health` | Public | Liveness and readiness probe reporting vector store chunk count |
| `GET` | `/metrics` | `operator` / `admin` | Aggregated latency, agent/tool counters, and guardrail/handoff stats |
| `GET` | `/alerts` | `operator` / `admin` | Production alerts (`HIGH_LATENCY`, `SECURITY_GUARDRAIL`, `HUMAN_HANDOFF`, `RATE_LIMIT`, `TOKEN_BUDGET`) |
| `GET` | `/traces` / `/traces/{trace_id}` | `operator` / `admin` | Sanitized execution traces and span inspector |
| `POST` | `/evals/run` | `operator` / `admin` | Execute Ragas quantitative evaluation benchmark and return scorecard |
| `GET` | `/docs` | Public | Interactive Swagger / OpenAPI documentation |

### Sample Authenticated Flow (PowerShell / `cURL`)

```bash
# 1. Mint a merchant Bearer JWT scoped to cliente1988
TOKEN=$(curl -s -X POST http://localhost:8000/auth/token \
  -H "Content-Type: application/json" \
  -d '{"user_id": "cliente1988", "role": "merchant"}' | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 2. Query the multi-agent API (cross-tenant user_id returns 403 Forbidden)
curl -X POST http://localhost:8000/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "What'\''s the difference between the Get Clássica and the Get Smart?", "user_id": "cliente1988"}'

# 3. Mint an operator token and resume a paused HITL handoff
OP_TOKEN=$(curl -s -X POST http://localhost:8000/auth/token \
  -H "Content-Type: application/json" \
  -H "X-Bootstrap-Key: getnet-bootstrap-operator-key" \
  -d '{"user_id": "operator_1", "role": "operator"}' | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -X POST http://localhost:8000/handoffs/<thread_id>/resume \
  -H "Authorization: Bearer $OP_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"decision": "approved", "operator_note": "Chargeback dispute reviewed; settlement cleared."}'
```

### Sample JSON Response

```json
{
  "response": "Hello, cliente1988! When comparing the Get Clássica and the Get Smart...",
  "user_id": "cliente1988",
  "routed_agents": ["router_agent", "knowledge_agent", "personality_agent"],
  "tools_used": ["retrieve_getnet_knowledge"],
  "sources": ["https://site.getnet.com.br/maquininhas/"],
  "confidence_score": 0.923,
  "guardrail_triggered": false,
  "handoff_required": false,
  "handoff_status": "none",
  "thread_id": "thr-trc-b44deac865ba",
  "human_decision": null,
  "trace_id": "trc-b44deac865ba",
  "latency_ms": 110.35,
  "effective_slo_target_ms": 7000.0,
  "slo_tier": "fast_path",
  "slo_violated": false,
  "total_tokens": 0
}
```

---

## 7. Testing Strategy, Ragas Evals & CI Quality Gate

### Automated Test Pyramid (`117/117` Passing)

1. **Unit Tests (`tests/unit/`):**
   - `test_auth_and_rate_limit.py`: JWT creation/expiry (`401`), RBAC (`403`), anti-IDOR tenant isolation, message `max_length` (`422`), sliding-window rate limits (`429`), and daily token budget caps.
   - `test_router.py`: Intent classification, multi-intent hybrid routing, query rewriting, and 3-tier business risk classification (`high`, `medium`, `low`).
   - `test_orchestrator.py`: Risk-gated conditional escalation and end-to-end LangGraph `interrupt()` / `Command(resume=...)` HITL lifecycle.
   - `test_rag.py`: Markdown chunking, ChromaDB indexing, top-$k$ retrieval accuracy.
   - `test_tools.py`: All 6 LangChain tools plus SQLite ticket reload persistence.
   - `test_guardrails.py`: Normalized/base64 prompt-injection blocking and PCI PAN / CVV / CPF / CNPJ / Bearer redaction.
   - `test_observability.py`: Trace spans, log/trace PCI sanitization, Ragas metrics & threshold gates, multi-tier dynamic SLOs, and alerting rules.
   - `test_session_memory.py`: SQLite-backed session memory persistence across reloads and ring-buffer pruning.
2. **API Contract Tests (`tests/integration/test_api_endpoints.py`):**
   - Validates `/auth/token`, `/auth/session`, `/auth/logout`, `/chat`, `/chat/stream`, `/handoffs`, `/handoffs/{thread_id}/resume`, `/health`, `/metrics`, `/alerts`, `/traces/{id}`, `/evals/run`, `/dashboard`, and favicons (`200`, `401`, `403`, `404`, `409`, `422`, `429`).
3. **End-to-End Challenge Scenarios (`tests/integration/test_challenge_scenarios.py` & `test_multi_turn_chat.py`):**
   - Verifies all 10 official challenge scenarios + hybrid, HITL escalation, guardrail adversarial, and multi-turn contextual follow-up chains.

### Ragas Evaluation Scorecard (`scripts/evaluate.py --enforce-thresholds`)

Verified across all 13 scenarios in `data/eval_dataset.json` (`offline_deterministic` CI mode; switches to `ragas_live` automatically when `OPENAI_API_KEY` is configured):

| Metric | Measured Result | CI Gate / Target |
| :--- | :---: | :---: |
| **Official 10 Challenge Scenarios** | **10 / 10** | `10 / 10` |
| **Routing Accuracy** | **100.0%** | `100.0%` |
| **Tool Selection Accuracy** | **100.0%** | `100.0%` |
| **Rubric Groundedness** | **100.0%** | `100.0%` |
| **Ragas Faithfulness** | **0.9284** | $\ge 0.7000$ |
| **Ragas Answer Relevancy** | **0.9273** | Monitored |
| **Ragas Context Precision** | **1.0000** | Monitored |
| **Ragas Context Recall** | **0.8328** | Monitored |
| **Hallucination Rate** (`1 - Faithfulness`) | **0.0716** | $\le 0.3000$ |

```powershell
# Run full test suite (117 passed)
.\.venv\Scripts\python.exe -m pytest -v

# Run Ragas evaluation benchmark with CI threshold enforcement
.\.venv\Scripts\python.exe scripts/evaluate.py --enforce-thresholds

# Validate all OpenSpec specifications strictly
openspec validate --all --strict
```

Automated CI runs on every push/PR via [`.github/workflows/ci.yml`](.github/workflows/ci.yml) executing `pytest`, `scripts/evaluate.py --enforce-thresholds`, and `openspec validate --all --strict`.

---

## 8. Interactive Visual Dashboard (`GET /dashboard`)

Access `http://localhost:8000/dashboard` in your browser (authenticated via operator Bootstrap Key or Bearer JWT):

- **Operator Security & HITL Review Queue:** View paused `interrupt()` threads (`pending_human_review`), enter specialist guidance notes, and click **Approve & Resume** directly from the UI (`POST /handoffs/{thread_id}/resume`), or sign out via `POST /auth/logout`.
- **Scenario Console & Live Tree Map:** One-click presets for all 10 official scenarios + hybrid, security, and HITL escalation flows streaming live SSE node states.
- **Latency & Multi-Tier SLO Chart:** Dynamic SVG chart tracking Fast Path ($\le 7\text{s}$) and Complex Path ($\le 18\text{s}$) SLOs alongside token usage and trace spans.

---

## 9. Architectural Trade-Offs

- **Self-Contained Auth & SQLite Persistence vs. External Infra:** Signed `HS256` JWTs + `HttpOnly` cookies and SQLite WAL persistence (`SqliteSaver`, `SessionStore`, `TicketStore`, `HandoffStore`) give zero-external-dependency container startup while keeping clean repository boundaries ready for an external IdP (Keycloak/Okta) or Postgres/Redis in multi-replica deployments.
- **Normalized Regex Guardrails vs. Secondary Guard LLM:** Ingress validation applies Unicode `NFKC` + homoglyph/zero-width normalization and base64 decoding at sub-millisecond latency without extra token spend; a lightweight classifier can be layered in front if paraphrase-heavy adversarial traffic increases.

---

## 10. Repository File Structure

```text
getnet-multi-agent/
├── .github/workflows/ci.yml        # CI pipeline: pytest + Ragas --enforce-thresholds + OpenSpec strict check
├── Dockerfile                      # Non-root (appuser) container with pre-seeded ChromaDB & healthcheck
├── docker-compose.yml              # Production compose with persistent ./data/runtime & ./logs volumes
├── pyproject.toml                  # Package metadata, dependencies, and pytest configuration
├── requirements.txt                # Pinned Python dependencies (FastAPI, LangGraph, Ragas, PyJWT, etc.)
├── README.md                       # System architecture, security, Ragas, and runbook documentation
├── data/
│   ├── chroma_db/                  # Persistent ChromaDB vector index
│   ├── eval_dataset.json           # 10 official scenarios + hybrid, HITL, and adversarial cases + references
│   ├── merchants.json              # Mock merchant telemetry & settlements (cliente1988)
│   └── knowledge_base/
│       └── getnet_products.md      # Curated ground-truth corpus for Getnet POS lineup & rules
├── openspec/
│   ├── specs/                      # 6 canonical specs (incl. api-security-rbac, guardrails-escalation, api-observability)
│   └── changes/archive/            # Archived OpenSpec proposals, designs, deltas, and completed tasks
├── scripts/
│   ├── evaluate.py                 # Ragas quantitative evaluation CLI & LangSmith Experiment runner
│   └── ingest_kb.py                # ChromaDB ingestion and live Getnet domain scraper
├── src/
│   ├── main.py                     # FastAPI application entrypoint and lifespan hooks
│   ├── agents/                     # 5 LangGraph agents (router, knowledge, support, escalation, personality)
│   ├── api/
│   │   ├── auth.py                 # HS256 JWT issuance/verification, RBAC, anti-IDOR & HttpOnly cookie auth
│   │   ├── rate_limit.py           # Sliding-window rate limiter & daily/request token budget tracker
│   │   ├── routes.py               # Protected HTTP endpoints (/auth/*, /chat*, /handoffs*, /traces*, /evals/run)
│   │   ├── schemas.py              # Pydantic request/response contracts & HandoffResumeRequest
│   │   └── dashboard.py            # Operator login gate + interactive Visual Explainer & HITL Queue UI
│   ├── config/settings.py          # Typed Pydantic Settings (auth, budgets, SQLite paths, Ragas thresholds)
│   ├── guardrails/
│   │   ├── redaction.py            # Shared PCI-DSS PAN/CVV, LGPD CPF/CNPJ & Bearer secret sanitizer
│   │   └── validator.py            # Unicode/base64-normalized ingress guardrail & egress PII redaction
│   ├── observability/
│   │   ├── logger.py               # Structlog JSON logger with automatic PII sanitization processor
│   │   └── tracer.py               # Execution trace recorder, multi-tier SLOs & operational/budget alerts
│   ├── orchestration/
│   │   ├── graph.py                # 5-Agent StateGraph with SqliteSaver, interrupt() & Command(resume=...)
│   │   ├── persistence.py          # Shared SQLite WAL helpers & persistent HandoffStore
│   │   ├── session_store.py        # SQLite-backed multi-turn conversational history store
│   │   └── state.py                # TypedDict orchestration state & RouterPlan risk-tier contract
│   ├── rag/                        # Live scraper, semantic chunker, and ChromaDB hybrid vector store
│   └── tools/                      # Knowledge, SQLite-backed support ticket, and escalation tools
└── tests/
    ├── conftest.py                 # In-memory DB isolation, rate-limit reset & merchant/operator auth fixtures
    ├── unit/                       # 8 unit suites (incl. test_auth_and_rate_limit.py)
    └── integration/                # API contracts, browser cookie auth, HITL pause/resume & 13 scenarios
```
