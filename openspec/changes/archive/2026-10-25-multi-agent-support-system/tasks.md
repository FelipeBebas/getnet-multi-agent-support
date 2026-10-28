# Tasks

## 1. Project Scaffolding, Configuration & Observability Core

- [x] 1.1 Create directory structure (`src/`, `data/`, `scripts/`, `tests/`), `pyproject.toml`, `requirements.txt`, and `.env.example` (including OpenAI, LangSmith `LANGCHAIN_TRACING_V2`/`LANGCHAIN_API_KEY`/`LANGCHAIN_PROJECT`, and optional Langfuse variables), and verify all files exist and dependencies install cleanly
- [x] 1.2 Implement centralized configuration in `src/config/settings.py` using `pydantic-settings` (LLM provider, OpenAI models, ChromaDB path, LangSmith & Langfuse keys, guardrail & alerting thresholds) and verify settings load with default values via `python -c "from src.config.settings import settings; print(settings.app_name)"`
- [x] 1.3 Implement structured JSON logging (`src/observability/logger.py`) and execution trace, metrics, and SLO/security alerting recorder (`src/observability/tracer.py`) with native LangSmith (`@traceable`) and optional Langfuse support, and verify unit tests for trace span creation, metrics aggregation, and alert triggers pass

## 2. Knowledge Base (RAG Pipeline) & External Web Search Tools

- [x] 2.1 Create the curated Getnet ground-truth knowledge base corpus (`data/knowledge_base/getnet_products.md`) covering `https://www.getnet.net/en`, the full POS catalog (*Get Tap*, *Get Mini*, *Get Lite*, *Get Clássica*, and *Get Smart*), *Pix* (bank domicile rules), *Antecipação de Recebíveis* (punctual & automatic), *Crediário* (up to 48x installments), and *Link de Pagamento / GetPay on WhatsApp*, and verify the corpus file contains all required product sections and official `source_url` metadata
- [x] 2.2 Implement the RAG ingestion and vector store module (`src/rag/ingest.py`, `src/rag/vector_store.py`, and `scripts/ingest_kb.py`) supporting multi-URL live scraping (`https://www.getnet.net/en` and `https://site.getnet.com.br` product/FAQ pages) plus markdown chunking into persistent ChromaDB, and verify ingestion and top-$k$ retrieval via `pytest tests/unit/test_rag.py`
- [x] 2.3 Implement Knowledge Agent tools (`src/tools/knowledge_tools.py`): `retrieve_getnet_knowledge` (ChromaDB RAG with automatic live Getnet domain web-search fallback when queried about newly launched/unlisted Getnet products) and `web_search_general` (DuckDuckGo/Tavily + live Open-Meteo weather & Frankfurter/AwesomeAPI Euro exchange rate), and verify unit tests in `tests/unit/test_tools.py` pass

## 3. Customer Support Data Store & Domain Tools

- [x] 3.1 Create the merchant mock database (`data/merchants.json`) containing profile, settlement batches, POS terminal telemetry, transaction decline codes, and tickets for `cliente1988` (and secondary test merchants), and verify JSON schema validity
- [x] 3.2 Implement Customer Support Agent tools (`src/tools/support_tools.py`): `get_merchant_settlement_status`, `diagnose_pos_and_transactions`, and `manage_support_ticket` (plus escalation handoff tool in `src/tools/escalation_tools.py`), and verify all 3+ support tools pass unit tests in `tests/unit/test_tools.py` for `cliente1988` and unknown users

## 4. Guardrails & Multi-Agent Orchestration (LangGraph)

- [x] 4.1 Implement Input and Output Guardrails (`src/guardrails/validator.py`) for prompt injection detection, toxic/unsafe request blocking, and PII/PAN masking, and verify guardrail unit tests pass in `pytest tests/unit/test_guardrails.py`
- [x] 4.2 Implement the 5 specialized agents (`src/agents/router_agent.py`, `src/agents/knowledge_agent.py`, `src/agents/support_agent.py`, `src/agents/escalation_agent.py`, `src/agents/personality_agent.py`) with high-precision system prompts and LLM/fallback execution, and verify router classification tests pass in `pytest tests/unit/test_router.py`
- [x] 4.3 Implement the LangGraph orchestration state and workflow (`src/orchestration/state.py`, `src/orchestration/graph.py`) connecting Guardrails, Router Agent, Knowledge Agent, Customer Support Agent, Human Escalation Agent, and Personality Agent, and verify single-agent and sequential multi-agent routing in unit/integration tests

## 5. FastAPI HTTP Service, Visual Dashboard, Evaluation Suite, Dockerization & Documentation

- [x] 5.1 Implement FastAPI schemas, endpoints, and interactive visual explainer/observability dashboard (`src/api/schemas.py`, `src/api/routes.py`, `src/api/dashboard.py`, `src/main.py`) exposing `POST /chat` (and `POST /`), `GET /health`, `GET /metrics`, `GET /alerts`, `GET /traces/{trace_id}`, and `GET /dashboard`, and verify endpoint contract tests pass via `pytest tests/integration/test_api_endpoints.py`
- [x] 5.2 Create the versioned evaluation dataset (`data/eval_dataset.json`) and implement the 10-scenario + hybrid + adversarial integration test suite (`tests/integration/test_challenge_scenarios.py`) and automated evaluation benchmark CLI (`scripts/evaluate.py` with local scorecard and optional LangSmith dataset evaluation), and verify all 10 official PDF test scenarios pass with 100% routing and tool accuracy
- [x] 5.3 Create `Dockerfile`, `docker-compose.yml`, and `.dockerignore`, and verify container configuration and build instructions
- [x] 5.4 Write comprehensive `README.md` covering build/configuration/run instructions, test execution, multi-agent orchestration architecture, message workflow, RAG pipeline (`ingestion → storage → retrieval → generation`), LLM tools, guardrails, and observability/evaluation strategy, and verify all documented commands match the codebase

## Workflow follow-up

- Run `openspec validate "multi-agent-support-system" --strict` to confirm all spec deltas and planning artifacts remain valid.
- Archive the change (`openspec archive "multi-agent-support-system"`) after implementation and verification are complete.
