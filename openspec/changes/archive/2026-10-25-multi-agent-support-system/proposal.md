# Proposal: Getnet Multi-Agent Support System

## Why

Merchants and customers interacting with Getnet require accurate, low-latency answers across very different intents: institutional product questions (e.g., comparing *Get Clássica* vs. *Get Smart*, Pix requirements, *Crediário* installments, *Antecipação* of receivables), general real-time queries (e.g., weather forecast in Porto Alegre, Euro exchange rate), and personalized account/technical troubleshooting tied to their `user_id` (e.g., settlement deposit schedules, declined transactions, POS connectivity failures). A single monolithic prompt cannot reliably ground product answers, invoke account-specific tools, enforce safety guardrails, and maintain a consistent brand voice; a Spec-Driven Multi-Agent Orchestration solves this by decomposing routing, knowledge retrieval (RAG + Web Search), customer support tool execution, human handoff, and observability into cohesive, testable components.

## What Changes

- **Introduce Multi-Agent Orchestration Graph (`agent-orchestration`)**:
  - Implement a **Router Agent** as the primary entry point that classifies intent, plans single-agent or multi-agent execution sequences, and routes context.
  - Implement a **Personality & Response Synthesis Agent** (as depicted in the reference architecture workflow) that normalizes outputs from specialized agents into a helpful, clear, and consistent Getnet support tone.
- **Introduce Hybrid Knowledge Agent (`knowledge-rag`)**:
  - Build a complete **RAG pipeline** (`ingestion → chunking → embedding → ChromaDB storage → retrieval → grounded generation`) seeded with official Getnet sources (`https://www.getnet.net/en`, Getnet Brasil product documentation for *Get Clássica*, *Get Smart*, *Pix*, *Crediário*, *Antecipação*, and *Link de Pagamento / WhatsApp*).
  - Equip the Knowledge Agent with a **Web Search Tool** (DuckDuckGo / Tavily fallback) to handle general-purpose, real-time queries such as weather forecasts and foreign exchange rates.
- **Introduce Customer Support Agent & Domain Tools (`customer-support`)**:
  - Implement a **Customer Support Agent** conditioned on `user_id` with **3 specialized tools** (exceeding the minimum of 2):
    1. `get_merchant_receivables_and_settlement`: Queries settlement status, yesterday's sales deposit schedule, and bank account/receivables details for a given `user_id`.
    2. `diagnose_terminal_and_transactions`: Inspects POS terminal telemetry, connectivity diagnostics, and recent transaction decline error codes for a given `user_id`.
    3. `create_or_check_support_ticket`: Opens or checks technical assistance/replacement tickets when hardware or transaction issues persist.
- **Introduce Guardrails & Custom Escalation Agent (`guardrails-escalation`)**:
  - Implement **Input/Output Guardrails** to detect and block prompt injections, unsafe/toxic content, or sensitive PII leaks before and after agent execution.
  - Implement a **4th Custom Agent — Human Escalation & Handoff Agent** that triggers when confidence is below threshold, when guardrails flag sensitive account disputes, or when severe unresolved POS errors require a human specialist.
- **Introduce HTTP API, Containerization & Observability/Evals (`api-observability`)**:
  - Expose a `POST /chat` (and `POST /api/v1/message` alias) endpoint in FastAPI accepting `{"message": "...", "user_id": "..."}` and returning the final response along with structured orchestration metadata (`routed_agents`, `tools_used`, `sources`, `trace_id`, `handoff_required`).
  - Provide production-ready `Dockerfile` and `docker-compose.yml` for one-command build and execution.
  - Implement **Structured JSON Logging**, **Execution Tracing** (Langfuse / OpenTelemetry compatible + local trace store), and an **Automated Evaluation Suite** testing all 10 official challenge scenarios plus adversarial guardrail cases.

## Capabilities

### New Capabilities
- `agent-orchestration`: Multi-agent workflow orchestration via LangGraph, covering the Router Agent, multi-step agent dispatch, shared state schema, and the Personality/Output formatting agent.
- `knowledge-rag`: End-to-end RAG pipeline (`ingestion → storage → retrieval → generation`) grounded on Getnet's website/product catalog and a real-time Web Search tool for general-purpose queries.
- `customer-support`: Personalized merchant support agent leveraging `user_id` context and domain tools for settlements/receivables, POS terminal & transaction decline diagnostics, and ticket creation.
- `guardrails-escalation`: Input/output safety guardrails and a 4th custom Human Escalation & Handoff Agent for low-confidence or high-risk requests.
- `api-observability`: FastAPI HTTP service contract, Docker/Docker Compose packaging, structured telemetry/tracing, and automated scenario evaluation pipeline.

### Modified Capabilities
<!-- None — greenfield repository -->

## Impact

- **Codebase Structure**: Introduces `src/` (`api/`, `agents/`, `rag/`, `tools/`, `guardrails/`, `observability/`, `config/`), `data/` (curated & scraped Getnet corpus + mock merchant database including `cliente1988`), `tests/` (unit, integration, and the 10-scenario evaluation suite), `Dockerfile`, `docker-compose.yml`, `pyproject.toml`, `.env.example`, and `README.md`.
- **External Dependencies**: Python 3.12, `fastapi`, `uvicorn`, `pydantic`, `langgraph`, `langchain-core`, `langchain-openai`, `chromadb`, `beautifulsoup4`, `httpx`, `duckduckgo-search`, `structlog`, `pytest`, `pytest-asyncio`.
- **APIs & Operations**: Exposes port `8000` with `/chat` (`POST`), `/health` (`GET`), and `/metrics` (`GET`) endpoints, fully containerized via Docker.
