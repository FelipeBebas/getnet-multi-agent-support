# Proposal: Authentic RAG & Web Search, LangSmith Evals, and Tree Dashboard

## Why

Live testing of the v1.0 baseline exposed four critical gaps that must be resolved before final submission:
1. **Hardcoded Fallback Mocks ("Maquiagem")**: Without an active `.env` (`OPENAI_API_KEY`), agents fell back to hardcoded English `if/elif` templates (`_synthesize_grounded_knowledge_fallback`), static DuckDuckGo placeholder snippets, and an artificial confidence floor (`max(0.65, ...)`), causing out-of-corpus Getnet questions like `"Quando a getnet foi inaugurada?"` to return an unrelated English paragraph about *Crediário* instead of invoking live Web Search or escalating.
2. **Timezone Offset Bug (`UTC` vs `America/Sao_Paulo`)**: Weather forecast queries executed after 21:00 BRT (`UTC-3`) computed `"tomorrow"` using `timezone.utc`, shifting the forecast date forward by 2 days (`2026-10-27` instead of `2026-10-26`).
3. **LangSmith Metrics & Automated Evals**: While traces can be exported, `scripts/evaluate.py` only created a dataset without executing `langsmith.evaluation.evaluate` with custom evaluators (`routing_accuracy`, `tool_accuracy`, `rubric_groundedness`, `llm_faithfulness`) to populate full experiment scorecards and metrics inside the LangSmith UI.
4. **Dashboard Topology & System Design**: The `/dashboard` UI currently renders a flat horizontal row of boxes rather than a true **Hierarchical Tree (DAG)** showing the Router branching into specialized agents and their respective tools, and awaits a custom System Design overhaul.

## What Changes

- **Eliminate Hardcoded Answer Mocks & Enforce Dynamic Corrective Web Search (`knowledge-rag`)**:
  - Remove hardcoded `if/elif` canned English product paragraphs and static search-failure placeholders from `src/agents/knowledge_agent.py` and `src/tools/knowledge_tools.py`.
  - Enable `OpenAIEmbeddings` (`text-embedding-3-small`) in `src/rag/vector_store.py` when `OPENAI_API_KEY` is configured.
  - Implement true **Dynamic Corrective RAG-to-Web-Search Escalation**: when any query routed to `product_rag` has low similarity (`< rag_min_similarity_threshold`) or the retrieved RAG chunks do not actually contain the answer to the user's question (e.g., out-of-corpus questions like `"Quando a getnet foi inaugurada?"`), the Knowledge Agent discards the irrelevant RAG chunks and automatically invokes `web_search_general` to search the live internet, answering from the real web results (or escalating to the Human Escalation Agent if confidence remains `< 0.60`).
  - Fix date resolution in `_fetch_weather_forecast` to automatically detect the user's/target location's local timezone (`timezone=auto` in Open-Meteo + `datetime.now().astimezone()`) instead of forcing `timezone.utc`.
- **Full LangSmith Metrics & Experiment Evals + Hierarchical Tree Dashboard (`api-observability`)**:
  - Upgrade `scripts/evaluate.py` (and expose `POST /evals/run`) to run **`langsmith.evaluation.evaluate`** with 4 custom evaluators (`routing_accuracy`, `tool_accuracy`, `rubric_groundedness`, `llm_faithfulness_judge`), recording latency, token usage, and experiment scorecards directly in the LangSmith dashboard.
  - Refactor `GET /dashboard` (`src/api/dashboard.py`) from a linear row of boxes into a **Hierarchical Tree (DAG) Visualization** (`Input Guardrail` → `Router Agent` → branching to `Knowledge Agent`, `Customer Support Agent`, `Escalation Agent` + child Tool nodes → converging into `Personality Agent` → `Output Guardrail`) and prepare the component structure for the user's custom System Design.

## Capabilities

### New Capabilities
<!-- None -->

### Modified Capabilities
- `knowledge-rag`: Enforces zero-mockup grounded generation, institutional history coverage, automatic escalation from low-similarity RAG to real `web_search_general` (and human handoff when `< 0.60`), and Brazil timezone (`America/Sao_Paulo`, `UTC-3`) date calculation for weather forecasts.
- `api-observability`: Adds full LangSmith Experiment execution (`langsmith.evaluation.evaluate` with custom metrics/evaluators in LangSmith UI) and refactors `GET /dashboard` to render a hierarchical Tree/DAG workflow with support for a custom System Design.

## Impact

- **Affected Code**: `src/tools/knowledge_tools.py`, `src/agents/knowledge_agent.py`, `src/agents/router_agent.py`, `src/rag/vector_store.py`, `data/knowledge_base/getnet_products.md`, `scripts/evaluate.py`, `src/api/routes.py`, `src/api/dashboard.py`, `tests/unit/test_tools.py`, `tests/integration/test_challenge_scenarios.py`.
- **Configuration**: Uses `.env` (created from `.env.example` in the project root) with `OPENAI_API_KEY`, `LANGCHAIN_TRACING_V2=true`, `LANGCHAIN_API_KEY`, and `LANGCHAIN_PROJECT`.
