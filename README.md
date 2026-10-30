# Getnet Multi-Agent Support System

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-StateGraph-orange.svg)](https://langchain-ai.github.io/langgraph/)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-Vector_Store-green.svg)](https://www.trychroma.com/)
[![OpenSpec](https://img.shields.io/badge/Spec--Driven-OpenSpec-purple.svg)](https://github.com/openspec)
[![Tests Passing](https://img.shields.io/badge/Tests-100%2F100%20PASS-brightgreen.svg)](tests/)
[![Challenge Benchmark](https://img.shields.io/badge/Challenge%20Scenarios-10%2F10%20(100%25)-success.svg)](scripts/evaluate.py)

Production-grade **Spec-Driven Multi-Agent Support System** engineered for the **Getnet AI Hardcore Engineer Challenge**. Built with **Python 3.12**, **FastAPI**, **LangGraph**, **ChromaDB**, **LangSmith**, and **OpenSpec**.

---

## 🎥 Video Presentation & Walkthrough

[![Getnet Multi-Agent Solution Walkthrough](docs/assets/video-thumbnail.png)](https://drive.google.com/file/d/1MhL4jDibYF79vLd7Dm_1SuRnT12zpLuW/view?usp=sharing)

<p align="center">
  <em>▶️ <b><a href="https://drive.google.com/file/d/1MhL4jDibYF79vLd7Dm_1SuRnT12zpLuW/view?usp=sharing" target="_blank" rel="noopener noreferrer">Assistir ao Walkthrough da Solução (13 min) no Google Drive</a></b></em>
</p>

> **Apresentação em Vídeo da Solução:** Walkthrough guiado de ~13 minutos demonstrando a arquitetura multiagente com 5 agentes em LangGraph, as guardrails bidirecionais de segurança (PCI-DSS & LGPD), a busca híbrida com ChromaDB, os testes automatizados e a demonstração ao vivo no dashboard.

---

## 1. Architecture Overview, Design Choices & Message Workflow

The system implements a deterministic, fully observable **5-Agent LangGraph (`StateGraph`) Orchestration** protected by bidirectional security and privacy **Guardrails**, exceeding the challenge baseline of 3 agents and 2 tools:

```mermaid
flowchart TD
    User(["POST /chat\n{message, user_id}"]) --> InGuard["Input Guardrail\n(Prompt Injection & Security Defense)"]
    InGuard -- "Blocked" --> OutGuard["Output Guardrail\n(PCI-DSS PAN & LGPD CPF Masking)"]
    InGuard -- "Allowed" --> Router["Agent 1: Router Agent\n(Contextual Rewriting & Intent Classification)"]

    Router -- "knowledge" --> Knowledge["Agent 2: Knowledge Agent\n(RAG & Domain Fallback)"]
    Router -- "customer_support" --> Support["Agent 3: Customer Support Agent\n(Merchant Telemetry & Settlements)"]
    Router -- "escalation" --> Escalation["Agent 4: Human Escalation Agent\n(Handoff & Priority Queues)"]
    Router -- "hybrid" --> Knowledge

    Knowledge <--> KTools[("Knowledge Tools:\n1. retrieve_getnet_knowledge\n2. web_search_general")]
    Support <--> STools[("Support Tools:\n1. get_merchant_settlement_status\n2. diagnose_pos_and_transactions\n3. manage_support_ticket")]
    Escalation <--> ETools[("Escalation Tools:\n1. dispatch_human_handoff\n2. manage_support_ticket")]

    Knowledge --> QueueGate{"Next queued agent\nor Low Confidence & Risk?"}
    Support --> QueueGate

    QueueGate -- "Next: customer_support" --> Support
    QueueGate -- "Low Conf & High/Medium Risk" --> Escalation
    QueueGate -- "Complete / Low Risk" --> Personality["Agent 5: Personality Agent\n(Synthesis, Empathy & SSE Token Streaming)"]

    Escalation --> Personality
    Personality --> OutGuard
    OutGuard --> Final(["Structured JSON Response\n+ End-to-End Execution Trace"])
```

### Agent Roles & Responsibilities

1. **Agent 1 — Router Agent (`src/agents/router_agent.py`)**:
   - Primary gateway for all validated requests.
   - Operates a **Contextual Query Rewriter** (`rewrite_contextual_query`) to resolve elliptical multi-turn inquiries (e.g., *"what about yen?"* or *"quanto custa ela?"*) using prior dialogue context.
   - Emits a structured Pydantic contract (`RouterPlan`) that determines primary intent (`knowledge`, `customer_support`, `escalation`, `hybrid`, `out_of_scope`) and constructs an ordered execution queue (`agent_queue`).
2. **Agent 2 — Knowledge Agent (`src/agents/knowledge_agent.py`)**:
   - Resolves Getnet institutional, hardware, and financial queries via **3-Layer RAG** grounded in `https://www.getnet.net/en` and `https://site.getnet.com.br`.
   - Resolves general external queries (weather forecasts in Porto Alegre, Euro exchange rates) via **Resilient Web Search** (`web_search_general`).
   - Integrates an **Anti-Hallucination & Epistemic Uncertainty Gate**: if verified evidence is missing, emits `[INSUFFICIENT_EVIDENCE]`, calibrating confidence `< 0.60` to trigger automatic specialist escalation.
3. **Agent 3 — Customer Support Agent (`src/agents/support_agent.py`)**:
   - Resolves merchant-specific account and hardware troubleshooting for a given `user_id` (e.g., `cliente1988` - Padaria & Café Bela Vista Ltda).
   - Equips **3 domain tools**: settlement schedule lookup, POS network telemetry & ISO-8583 decline diagnostics, and technical support ticket management.
4. **Agent 4 (Bonus) — Human Escalation & Handoff Agent (`src/agents/escalation_agent.py`)**:
   - Activated on explicit human attendant requests, contested chargebacks, or whenever end-to-end resolution confidence falls below `< 0.60` on High/Medium business risk inquiries (while low-risk informational queries complete with epistemic caveats without opening human tickets).
   - Dispatches structured handoffs (`ESC-GN-XXXXXX`), opens linked CRM tickets (`TCK-2026-ESC`), and forwards conversation context to Tier-2 specialist desks.
5. **Agent 5 — Personality & Output Synthesis Agent (`src/agents/personality_agent.py`)**:
   - Synthesizes findings from upstream domain agents into an empathetic, brand-aligned response in the merchant's language (`en` or `pt`).
   - Supports real-time Server-Sent Events (SSE) token-by-token streaming at `POST /chat/stream`.

---

## 2. How We Leveraged LLM Tools

Rather than letting LLMs hallucinate tools or execute unstructured calls, the system enforces **strict software engineering principles around tool design**:

1. **Typed Pydantic Schemas & Decoupled Execution:**
   - Every tool is implemented as an isolated, deterministic Python function wrapped with LangChain's `@tool` decorator with full type hints and docstrings.
   - Tools can be executed independently by unit tests without launching an LLM, guaranteeing zero-flake testing and deterministic offline fallback.
2. **Domain-Specific Tool Inventory:**
   - `retrieve_getnet_knowledge(query, top_k)`: Queries persistent ChromaDB vector store with hybrid concept + n-gram similarity.
   - `web_search_general(query)`: Multi-provider search (Open-Meteo Weather API with local timezone resolution, European Central Bank Frankfurter API, AwesomeAPI, DuckDuckGo, Tavily, and Wikipedia Action API) filtered through an *Attributed Citations Gate*.
   - `get_merchant_settlement_status(user_id)`: Fetches yesterday's gross/net sales, settlement payout date (`D+1` vs `D+2`), deposit time windows, and masked bank accounts.
   - `diagnose_pos_and_transactions(user_id, issue_type)`: Inspects terminal hardware status, Wi-Fi 2.4GHz vs 5GHz band conflicts, 4G SIM APN session states, and ISO-8583 decline codes (e.g., Code 51 — Insufficient Funds).
   - `manage_support_ticket(user_id, issue_summary, action)`: Opens and checks technical assistance and terminal replacement tickets.
   - `dispatch_human_handoff(user_id, reason, conversation_summary, priority)`: Routes requests to Tier-2 support queues with protocol tracking.
3. **Trace Instrumentation & Observability:**
   - Every tool call is automatically captured inside a timed `TraceSpan` with inputs, outputs, execution duration, and token usage metrics recorded in `ExecutionTrace`.

---

## 3. RAG Pipeline (`Ingestion → Storage → Retrieval → Generation`)

The Retrieval-Augmented Generation pipeline is built across 4 distinct layers:

```mermaid
flowchart LR
    A["Layer 1: Ingestion\n(Live Scraper + Curated Markdown)"] --> B["Layer 2: Storage\n(ChromaDB + Hybrid Embeddings)"]
    B --> C["Layer 3: Retrieval\n(Top-k Cosine + Concept Rerank)"]
    C --> D["Layer 4: Grounded Generation\n(Anti-Hallucination & Citations)"]
    C -. "Similarity < 0.35" .-> E["Dynamic Fallback\n(Live Scoped Domain Search)"]
    E --> D
```

1. **Ingestion (`src/rag/ingest.py` & `scripts/ingest_kb.py`)**:
   - **Multi-URL Live Scraper**: Uses `httpx` and `BeautifulSoup4` to parse `https://www.getnet.net/en`, `https://site.getnet.com.br/maquininhas/`, `https://site.getnet.com.br/link-de-pagamento/`, and `https://site.getnet.com.br/duvidas/`.
   - **Curated Ground-Truth Corpus (`data/knowledge_base/getnet_products.md`)**: Verified knowledge covering the full terminal portfolio (*Get Tap*, *Get Mini*, *Get Lite*, *Get Clássica*, *Get Smart*), *Pix* bank domicile rules, *Antecipação de Recebíveis* (Automatic *Plano Receba Já* and Punctual), *Crediário* (up to **48 installments** with D+2 merchant payout), and *Payment Link (GetPay)* on WhatsApp.
   - **Semantic Chunking**: Splits sections by markdown headers and recursive paragraph overlap (`chunk_size=1450`, `chunk_overlap=180`), preserving provenance metadata (`source_url`, `title`, `section`, `product_tag`).
2. **Storage (`src/rag/vector_store.py`)**:
   - Persisted into **ChromaDB** (`data/chroma_db`) with `GetnetHybridEmbeddingFunction` (128-dimensional deterministic bilingual domain vector mapping payment concepts and hashed n-grams) plus optional `OpenAIEmbeddings` (`text-embedding-3-small`).
3. **Retrieval & Layer-3 Dynamic Fallback (`src/tools/knowledge_tools.py`)**:
   - Retrieves top-$k$ ($k=4$) chunks ranked by hybrid cosine similarity and lexical domain overlap boost.
   - **Corrective Domain Fallback**: If query similarity falls below `< 0.35` (e.g., newly launched products or historical events), the system automatically triggers a domain-scoped live search (`site:site.getnet.com.br OR site:getnet.net`).
4. **Grounded Generation (`src/agents/knowledge_agent.py`)**:
   - Answers are strictly synthesized from retrieved chunks with verified URLs attached to the response payload.

---

## 4. Spec-Driven Development & Development Timeline

Following the challenge guidelines (*"Use Spec Driven Development, and spend at most 60 min of screen time to develop the core-solution"*), the project lifecycle was organized into two deliberate phases:

1. **Phase 1 — Core Solution (Completed within 60 min screen time):**
   - Specification of contracts and architectures via OpenSpec in `openspec/specs/`.
   - Core 3-agent orchestration (`Router`, `Knowledge`, `Customer Support`) implemented with LangGraph.
   - Core FastAPI `POST /chat` endpoint handling incoming payloads.
   - Local RAG vector store and baseline support tools operational.
2. **Phase 2 — Enterprise Hardening & Bonus Engineering:**
   - **Security & Privacy Guardrails**: Prompt-injection ingress defense and egress PCI-DSS PAN / LGPD CPF masking.
   - **Quality & Testing**: 100 automated unit and integration tests with 100% pass rate.
   - **Observability & Reliability**: Multi-tier dynamic SLO latency alerting, LangSmith tracing, and token usage accounting.
   - **Bonus Agents & UX**: 4th Human Escalation Agent, 5th Personality Agent with SSE streaming, and the interactive `/dashboard`.

---

## 5. How to Build, Configure, and Run

### Option A: Run with Docker Compose (Recommended)

```bash
# 1. (Recommended) Copy .env.example to .env and configure your OPENAI_API_KEY / LANGCHAIN_API_KEY
cp .env.example .env

# 2. Build and start the service in background
docker compose up --build -d

# 3. Verify container health
curl http://localhost:8000/health
```

### Option B: Run with Standard Docker Commands

```bash
# Build the production image (pre-seeds persistent ChromaDB during build)
docker build -t getnet-multi-agent-support .

# Run container on port 8000
docker run --rm -p 8000:8000 --env-file .env.example getnet-multi-agent-support
```

### Option C: Run Locally with Python 3.12 (`uv` or `venv`)

```bash
# 1. Create virtual environment and install dependencies
uv venv --python 3.12 .venv
uv pip install --python .venv/Scripts/python.exe -r requirements.txt

# 2. Seed/verify the ChromaDB knowledge base
.venv/Scripts/python.exe scripts/ingest_kb.py --skip-live-scrape

# 3. Start the FastAPI application
.venv/Scripts/uvicorn.exe src.main:app --host 0.0.0.0 --port 8000
```

---

## 6. API Endpoints & Contract

Once running on `http://localhost:8000`, the application exposes:

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/chat` (aliases: `/`, `/api/v1/message`) | Main multi-agent endpoint accepting `{"message": "...", "user_id": "..."}` |
| `POST` | `/chat/stream` | Server-Sent Events (SSE) streaming node lifecycle events and token chunks |
| `GET` | `/dashboard` (also `/`) | Interactive Visual Explainer & Live Observability Dashboard |
| `GET` | `/health` | Liveness and readiness probe reporting vector store chunks count |
| `GET` | `/metrics` | Operational metrics (average/p95 latency, agent/tool counters, guardrail blocks) |
| `GET` | `/alerts` | Real-time production alerts (`HIGH_LATENCY_ALERT`, `SECURITY_GUARDRAIL_ALERT`, `HUMAN_HANDOFF_ALERT`) |
| `GET` | `/traces/{trace_id}` | Detailed execution trace and span inspector |
| `GET` | `/docs` | Interactive Swagger / OpenAPI documentation |

### Sample `cURL` Request

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What'\''s the difference between the Get Clássica and the Get Smart?", "user_id": "cliente1988"}'
```

### Sample JSON Response

```json
{
  "response": "Hello, cliente1988! When comparing the Get Clássica and the Get Smart...",
  "user_id": "cliente1988",
  "routed_agents": ["router_agent", "knowledge_agent", "personality_agent"],
  "tools_used": ["retrieve_getnet_knowledge"],
  "sources": ["https://site.getnet.com.br/maquininhas/"],
  "confidence_score": 0.95,
  "guardrail_triggered": false,
  "handoff_required": false,
  "trace_id": "trc-3843e2206eeb",
  "latency_ms": 110.35,
  "effective_slo_target_ms": 7000.0,
  "slo_tier": "fast_path",
  "slo_violated": false,
  "total_tokens": 0
}
```

---

## 7. Testing Strategy & Challenge Scenarios Verification

### Automated Test Pyramid

The test suite covers **100 automated tests** structured across 3 tiers:

1. **Unit Tests (`tests/unit/`)**:
   - `test_router.py`: Intent classification, multi-intent hybrid routing, query rewriting, and 3-tier business risk classification (`high`, `medium`, `low`).
   - `test_orchestrator.py`: LangGraph dispatching and risk-gated conditional escalation logic.
   - `test_rag.py`: Markdown parser, semantic chunking, ChromaDB indexing, top-$k$ retrieval accuracy.
   - `test_tools.py`: All 6 LangChain tools (settlement, POS telemetry, tickets, handoff, RAG, weather, FX).
   - `test_guardrails.py`: Ingress prompt injection blocking and egress PCI PAN / LGPD CPF masking.
   - `test_observability.py`: Trace recording, token counting, multi-tier dynamic SLO evaluation, alerting rules.
   - `test_session_memory.py`: In-memory session store, ring-buffer pruning, contextual dialogue history.
2. **API Contract Tests (`tests/integration/test_api_endpoints.py`)**:
   - Validates HTTP contracts for `/chat`, `/chat/stream`, `/health`, `/metrics`, `/alerts`, `/traces/{id}`, and `/dashboard`.
3. **End-to-End Challenge Scenario Tests (`tests/integration/test_challenge_scenarios.py`)**:
   - Directly executes the 10 official challenge scenarios + bonus cases from `data/eval_dataset.json`.

### Official 10 Challenge Scenarios Validation Matrix

| # | Official Challenge Scenario | Routed Agents | Tool Used | Ingestion / Grounding Source | Test Status |
| :-: | :--- | :--- | :--- | :--- | :-: |
| **01** | *"What's the difference between the Get Clássica and the Get Smart?"* | Router $\to$ Knowledge $\to$ Personality | `retrieve_getnet_knowledge` | `site.getnet.com.br/maquininhas/` | **PASSED** |
| **02** | *"What's the weather forecast in Porto Alegre tomorrow?"* | Router $\to$ Knowledge $\to$ Personality | `web_search_general` | Open-Meteo Weather API | **PASSED** |
| **03** | *"When will the money from yesterday's sales be deposited?"* | Router $\to$ Support $\to$ Personality | `get_merchant_settlement_status` | `data/merchants.json` (Settlement Engine) | **PASSED** |
| **04** | *"Do I need a bank account to receive my sales via Pix?"* | Router $\to$ Knowledge $\to$ Personality | `retrieve_getnet_knowledge` | `site.getnet.com.br/duvidas/` | **PASSED** |
| **05** | *"My card machine won't connect to the internet, what should I do?"* | Router $\to$ Support $\to$ Personality | `diagnose_pos_and_transactions` | `data/merchants.json` (POS Telemetry) | **PASSED** |
| **06** | *"How does receivables advance (antecipação) work with Getnet?"* | Router $\to$ Knowledge $\to$ Personality | `retrieve_getnet_knowledge` | `site.getnet.com.br/antecipacao-de-recebiveis/` | **PASSED** |
| **07** | *"What's the euro exchange rate today?"* | Router $\to$ Knowledge $\to$ Personality | `web_search_general` | European Central Bank / Frankfurter API | **PASSED** |
| **08** | *"My card machine is showing a transaction decline error."* | Router $\to$ Support $\to$ Personality | `diagnose_pos_and_transactions` | `data/merchants.json` (ISO-8583 Code 51 Switch) | **PASSED** |
| **09** | *"How many installments can I split a sale into with the crediário?"* | Router $\to$ Knowledge $\to$ Personality | `retrieve_getnet_knowledge` | `site.getnet.com.br/duvidas/crediario/` | **PASSED** |
| **10** | *"Can I sell through WhatsApp using the Payment Link?"* | Router $\to$ Knowledge $\to$ Personality | `retrieve_getnet_knowledge` | `site.getnet.com.br/link-de-pagamento/` | **PASSED** |

### How to Run Tests & Evaluation Benchmark

```bash
# Run complete test suite (100 passed)
.venv/Scripts/pytest.exe -v

# Run automated evaluation benchmark CLI (computes routing, tool & groundedness accuracy)
.venv/Scripts/python.exe scripts/evaluate.py
```

---

## 8. Observability, Alerting & Guardrails

1. **Structured JSON Logging:**  
   Implemented with `structlog` (`src/observability/logger.py`), binding `trace_id` and `user_id` into contextvars for request tracing.
2. **LangSmith Tracing:**  
   Native integration via `@traceable_step`. Setting `LANGCHAIN_TRACING_V2=true` and configuring `LANGCHAIN_API_KEY` streams all node and tool spans directly to LangSmith projects.
3. **Multi-Tier Dynamic SLO Alerting:**  
   Evaluates request latency against route complexity:
   - *Fast Path* ($\le 7.000$ ms): Local RAG, POS diagnostics, Guardrail blocks.
   - *Complex Path* ($\le 18.000$ ms): Deep Research, Web Search, Multi-Agent handoffs.
4. **Production Alerts (`GET /alerts`):**  
   Emits `HIGH_LATENCY_ALERT`, `SECURITY_GUARDRAIL_ALERT`, and `HUMAN_HANDOFF_ALERT`.
5. **Security & Privacy Guardrails:**  
   - Ingress: Blocks prompt injections (`instruction_override`, `system_prompt_extraction`) and financial fraud attempts.
   - Egress: Redacts 15-16 digit PAN card numbers (`PCI_PAN_MASKED`) and CPFs (`LGPD_CPF_MASKED`).

---

## 9. Interactive Visual Dashboard (`GET /dashboard`)

Access `http://localhost:8000/dashboard` in your browser for a self-contained visual console:

- **Scenario Console:** One-click presets for all 10 official challenge scenarios + hybrid, security, and human handoff cases.
- **Interactive Flow Tree Map:** Visualizes request progress in real time through Guardrails, Router Agent, Domain Specialists, and Synthesis.
- **Latency & SLO Chart:** Dynamic SVG scatter/bar chart rendering request latencies against Fast and Deep SLO thresholds.
- **Real-Time Token & Span Inspector:** Displays execution traces, spans, and token consumption directly in the UI.

---

## 10. Repository File Structure

```text
getnet/
├── Dockerfile                     # Container definition with ChromaDB pre-seeding & healthcheck
├── docker-compose.yml             # Container orchestration on port 8000 with volume logs
├── pyproject.toml                 # Package configuration, hatchling build, and pytest options
├── requirements.txt               # Pinned Python production and development dependencies
├── README.md                      # Comprehensive system documentation and architecture guide
├── data/
│   ├── chroma_db/                 # Persistent ChromaDB vector index files
│   ├── eval_dataset.json          # 10 official challenge scenarios + bonus evaluation dataset
│   ├── merchants.json             # Mock merchant database (cliente1988 telemetry & settlements)
│   └── knowledge_base/
│       └── getnet_products.md     # Curated ground-truth corpus for all 5 Getnet terminal models & rules
├── openspec/                      # Spec-Driven Development (SDD) specifications and task archives
│   └── specs/
│       ├── agent-orchestration/   # LangGraph workflow specifications
│       ├── knowledge-rag/         # RAG pipeline specifications
│       ├── customer-support/      # Support tools specifications
│       ├── guardrails-escalation/ # Security & handoff specifications
│       └── api-observability/     # API contracts & metrics specifications
├── scripts/
│   ├── evaluate.py                # Evaluation benchmark CLI & LangSmith Experiment runner
│   └── ingest_kb.py               # ChromaDB knowledge base ingestion and live scraper script
├── src/
│   ├── main.py                    # FastAPI application initialization and startup lifecycle
│   ├── agents/
│   │   ├── router_agent.py        # Agent 1: Router with Contextual Query Rewriter
│   │   ├── knowledge_agent.py     # Agent 2: Knowledge Agent (RAG + Web Search)
│   │   ├── support_agent.py       # Agent 3: Customer Support Agent (3 domain tools)
│   │   ├── escalation_agent.py    # Agent 4: Human Escalation & Priority Handoff Agent
│   │   └── personality_agent.py   # Agent 5: Personality Synthesis & Token Streaming Agent
│   ├── api/
│   │   ├── routes.py              # HTTP endpoints (/chat, /chat/stream, /health, /metrics, etc.)
│   │   ├── schemas.py             # Pydantic request/response validation models
│   │   └── dashboard.py           # Self-contained HTML Visual Explainer & Observability UI
│   ├── config/
│   │   └── settings.py            # Centralized typed settings via Pydantic Settings
│   ├── guardrails/
│   │   └── validator.py           # Input prompt-injection defense & Output PCI/LGPD masking
│   ├── observability/
│   │   ├── logger.py              # Structured JSON logging with Structlog contextvars
│   │   └── tracer.py              # Execution trace recorder, metrics & production alerting
│   ├── orchestration/
│   │   ├── graph.py               # 5-Agent LangGraph StateGraph builder & execution runner
│   │   ├── session_store.py       # Thread-safe in-memory session store for multi-turn chat
│   │   └── state.py               # TypedDict orchestration state schema
│   ├── rag/
│   │   ├── ingest.py              # Multi-URL live scraper & markdown semantic chunker
│   │   └── vector_store.py        # Persistent ChromaDB with hybrid embedding functions
│   └── tools/
│       ├── knowledge_tools.py     # RAG retrieval & resilient web search tools
│       ├── support_tools.py       # Settlement, POS telemetry, and ticket tools
│       └── escalation_tools.py    # Priority human specialist handoff dispatch tool
└── tests/
    ├── conftest.py                # Shared pytest fixtures and test clients
    ├── unit/                      # Unit test suites (router, rag, tools, guardrails, tracer)
    └── integration/               # Integration suites (api endpoints, 10 challenge scenarios, chat)
```
