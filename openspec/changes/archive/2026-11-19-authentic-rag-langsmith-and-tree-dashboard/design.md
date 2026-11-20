# Design: Authentic RAG & Web Search, LangSmith Evals, and Tree Dashboard

## Context

Following the v1.0 baseline implementation (`See proposal.md - Why`), interactive validation revealed four engineering improvements required to ensure 100% production authenticity:
1. Eliminating hardcoded `if/elif` fallback strings ("maquiagem") and artificial confidence clamping (`max(0.65, ...)`) when `.env` is configured or when a query falls outside the core POS catalog.
2. Fixing timezone drift in `_fetch_weather_forecast` where `timezone.utc` caused queries after 21:00 BRT (`UTC-3`) to report `"tomorrow"` as two days ahead.
3. Upgrading LangSmith integration from passive dataset creation to active **LangSmith Experiments (`langsmith.evaluation.evaluate`)** with custom evaluators so metrics and scorecards are visible directly in the LangSmith web UI.
4. Replacing the flat row of boxes in `GET /dashboard` with a **Hierarchical Tree (DAG)** visualization of the multi-agent architecture and preparing the UI for the user's custom System Design.

## Goals / Non-Goals

**Goals:**
- Ensure every agent (`Router`, `Knowledge`, `CustomerSupport`, `Personality`) uses real LLM calls (`ChatOpenAI`) and real embeddings (`OpenAIEmbeddings`) when `OPENAI_API_KEY` is provided in `.env`, without masking low-relevance RAG results behind canned English `if/elif` paragraphs.
- Ensure that when a user asks any question not covered by the RAG knowledge base (such as `"Quando a getnet foi inaugurada?"`), the system dynamically detects that the RAG chunks do not answer the question and automatically searches the internet via `web_search_general` rather than relying on pre-saved static answers.
- Ensure `_fetch_weather_forecast` automatically resolves dates using the target location's and user's local timezone (`timezone=auto` + `datetime.now().astimezone()`) rather than `timezone.utc`.
- Enable full **LangSmith Experiment Evals & Metrics** via `langsmith.evaluation.evaluate` in `scripts/evaluate.py` and `POST /evals/run`.
- Render a **Tree / DAG** orchestration diagram in `GET /dashboard` showing parent-child relationships (`Input Guardrail` → `Router` → `[Knowledge, Support, Escalation]` → `[Tools]` → `Personality` → `Output Guardrail`).

**Non-Goals:**
- Removing the `data/merchants.json` mock database for `cliente1988` (which is required by the challenge to simulate Getnet's internal merchant settlement/POS database).

## Decisions

### 1. Zero-Mockup Policy & Corrective RAG-to-Web-Search Escalation
- **Decision**:
  - Remove the `if tag == "crediario_installments": ...` hardcoded English paragraphs from `_synthesize_grounded_knowledge_fallback` in `src/agents/knowledge_agent.py`. Instead, synthesize directly from the actual retrieved chunk text (`top.get("content")`) only when `top_similarity >= settings.rag_min_similarity_threshold`.
  - Remove the fake static snippet in `_live_getnet_domain_search` (`"Official Getnet domain reference for query..."`). Instead, when RAG similarity is below threshold or the query asks about general/historical facts, invoke `web_search_general` (using upgraded `ddgs` / Wikipedia REST API / Tavily) and pass the real results to the LLM.
  - Remove `confidence = max(0.65, min(0.98, top_sim))` in `src/agents/knowledge_agent.py`. Confidence will reflect true retrieval/search quality so queries that fail both RAG and Web Search drop below `< 0.60` and trigger Agent 4 (`escalation_agent`).
- **Rationale**: Guarantees that the system never fabricates or returns unrelated product text when asked an unexpected question.

### 2. Automatic Local Timezone Detection (`timezone=auto` & `astimezone()`)
- **Decision**: Use `timezone=auto` in the Open-Meteo forecast request (so the API automatically resolves the exact timezone of the queried city's coordinates, e.g., Porto Alegre, São Paulo, or Madrid) and use `datetime.now().astimezone()` for local system clock resolution instead of hardcoded `timezone.utc`.
- **Rationale**: Automatically adapts to the user's local machine timezone and the queried city's UTC offset without hardcoding a single region.

### 3. LangSmith Experiments & Metrics (`langsmith.evaluation.evaluate`)
- **Decision**:
  - In `scripts/evaluate.py` (and `POST /evals/run` in `src/api/routes.py`), implement 4 LangSmith evaluator functions:
    1. `eval_routing_accuracy(run, example)`: Scores `1.0` if `routed_agents == expected_agents` else `0.0`.
    2. `eval_tool_accuracy(run, example)`: Scores `1.0` if all `expected_tools` were invoked else `0.0`.
    3. `eval_rubric_groundedness(run, example)`: Scores keyword/fact coverage in `[0.0, 1.0]`.
    4. `eval_llm_faithfulness(run, example)`: Uses `ChatOpenAI` as an LLM-as-a-Judge (when `OPENAI_API_KEY` is present) to grade factual faithfulness and tone in `[0.0, 1.0]`.
  - Invoke `langsmith.evaluation.evaluate(...)` when `--sync-langsmith` is passed (or `LANGCHAIN_API_KEY` is configured), creating a versioned experiment (`getnet-eval-...`) inside LangSmith with full latency, token, and accuracy charts.
- **Rationale**: Allows inspecting evaluation runs, traces, and metrics directly inside the LangSmith web dashboard rather than only in CLI or Swagger.

### 4. Hierarchical Tree / DAG Dashboard (`GET /dashboard`)
- **Decision**:
  - Replace the flat flex row (`#pipeline`) in `src/api/dashboard.py` with a hierarchical **Tree / DAG layout** rendered with SVG connectors / structured tree levels:
    - **Level 1**: `Input Guardrail` (Ingress Safety & Injection Filter)
    - **Level 2**: `Agent 1: Router Agent` (Intent Classifier & Dispatcher)
    - **Level 3 (Branches)**: `Agent 2: Knowledge Agent`, `Agent 3: Customer Support Agent`, `Agent 4: Escalation Agent`
    - **Level 4 (Leaf Tools)**: `retrieve_getnet_knowledge`, `web_search_general`, `get_merchant_settlement_status`, `diagnose_pos_and_transactions`, `manage_support_ticket`, `dispatch_human_handoff`
    - **Level 5 (Convergence)**: `Agent 5: Personality Agent` → `Output Guardrail (PCI/LGPD)`
  - Keep CSS variables and component tokens modular so the user's custom System Design can be applied cleanly in Task 2.2.

### 5. Architectural Invariants for Enterprise Robustness & Anti-Fragility (Non-Negotiable)
- **Decision**:
  1. **Entity Coverage Check & Anti-Inflation RAG Gate**:
     - Remove generic conversational phrasing (such as `"difference between"` and `"diferença entre"`) from concept cluster keyword lists in `src/rag/vector_store.py`.
     - Implement multi-entity verification in `src/agents/knowledge_agent.py`: when a query compares or references multiple entities (e.g., `"Get Clássica vs Get Bronze Water"`), the retriever must verify that all queried entities have authentic document support. If an entity is absent from Getnet's catalog, the system must explicitly declare that the entity does not exist in the official Getnet lineup, refusing to declare sufficiency on partial lexical matches.
  2. **Domain-Scoped External Search & Attributed Citations**:
     - Constrain product and corporate search queries in `src/tools/knowledge_tools.py` to official acquiring boundaries (`site:site.getnet.com.br` or `"Getnet"` domain enforcement).
     - Filter `sources` with an **Attributed Citations Gate**: only URLs whose content genuinely contributed facts to the final response text may be included in the response `sources` array, strictly preventing unrelated search hits (e.g., Wikipedia articles on philosophy, YouTube videos, or home decor blogs) from leaking into the audit trail.
  3. **Router Resilience & Out-of-Scope Isolation**:
     - Introduce an explicit `out_of_scope` / `unrecognized` intent in `src/agents/router_agent.py`.
     - Noisy, random, or out-of-domain messages (e.g., `"123 teste block"`, chit-chat) must receive a polite clarification prompt rather than being dumped into `knowledge_agent` product RAG or dropping into `escalation_agent` to create fake support tickets.
  4. **True Token Observability Across Agents**:
     - Extract `token_usage` from `ChatOpenAI.response_metadata` across all agents (`Router`, `Knowledge`, `Support`, `Personality`) and record them via `span.record_tokens(...)` so `total_tokens`, `prompt_tokens`, and `completion_tokens` reflect genuine LLM execution.
  5. **Deduplicated, Clean Offline Fallbacks**:
     - Eliminate naive concatenation of sliced markdown chunks in `_synthesize_grounded_knowledge_fallback`. Fallbacks must produce concise, deduplicated explanations without repeating section headers.

### 6. Multi-Turn Session Memory & Contextual Query Rewriting (Conversational Anti-Fragility)
- **Decision**:
  1. **In-Memory Session Store**:
     - Maintain an in-memory conversational history buffer (`SessionStore`) indexable by `user_id` (e.g. `cliente1988`), recording the last 8 dialogue turns with timestamps.
     - Inject `chat_history: list[dict[str, str]]` into `OrchestrationState` and make it accessible across all graph nodes.
  2. **Contextual Query Rewriter in Router Agent**:
     - Equip `RouterAgent` with an automated context rewriter: when an incoming message is elliptical, conversational, or refers back to prior topics (e.g., `"what about yen?"`, `"e no débito?"`, `"quanto custa ela?"`), the router uses the session history to synthesize an unambiguous, standalone query before determining routing plan, executing vector store retrieval, or calling tools.
  3. **Multi-Agent Prompt Contextualization**:
     - Provide the conversational history to the LLM system prompts of `KnowledgeAgent`, `CustomerSupportAgent`, and `PersonalityAgent`, ensuring that subsequent answers maintain consistent pronouns, references, and professional dialogue continuity.
  4. **External Tool Resilience**:
     - Fix `valid_hits` references in `src/tools/knowledge_tools.py` so that external search timeouts never trigger 500 Internal Server Errors.
     - Expand currency exchange retrieval (`_fetch_exchange_rate`) to dynamically support major world currencies (EUR, USD, JPY, GBP) with baseline offline references.

### 7. Calibração SRE Realista do Fast Path SLO (7.000 ms) vs. Arquitetura Multi-Agente Serial
- **Decision**: Calibrar a meta de SLO do Fast Path (`latency_slo_fast_path_ms`) de 4.000 ms para **7.000 ms** no backend (`src/config/settings.py` e `src/observability/tracer.py`) e na visualização do gráfico de execução do dashboard (`src/api/dashboard.py`).
- **Rationale**:
  - Uma rota padrão de conhecimento (*Fast Path*) encadeia deterministicamente três agentes seriais via LangGraph, cada um com uma chamada dedicada à API da OpenAI (`gpt-4o-mini`):
    1. `RouterAgent`: classificação semântica de intenção (~1.6s - 2.0s).
    2. `KnowledgeAgent`: extração factual fundamentada no contexto recuperado com contrato estrito anti-alucinação (~1.8s - 2.3s).
    3. `PersonalityAgent`: síntese institucional com persona Getnet e conformidade corporativa (~1.8s - 2.2s).
  - Somando a latência de rede transcontinental (Brasil ↔ EUA) e tempo de inferência, o piso físico do pipeline completo situa-se em $3 \times \sim 1.9\text{s} \approx \mathbf{5.7\text{ segundos}}$.
  - Manter uma meta irreal de 4.000 ms quando a física do pipeline nominal exige ~5.5s a 6.5s gera alertas espúrios de degradação (`HIGH_LATENCY_ALERT`) e polui a observabilidade.
  - O limiar de 7.000 ms reflete o teto operacional saudável para o pipeline de 3 agentes, disparando alertas de SLO apenas quando houver degradação de rede ou lentidão anômala na API externa (> 7s).

## Risks / Trade-offs

- **[Trade-off] Separação de Preocupações Multi-Agente (3 LLMs Seriais) vs. Latência Monolítica Agregada (4.000 ms)**:
  - *Opção Descartada*: Colapsar o `Knowledge Agent` e o `Personality Agent` em um único prompt monolítico ou pular o Router para forçar a latência artificialmente abaixo de 4.000 ms.
    - *Motivo do Descarte*: Destruiria a modularidade da arquitetura, aumentaria drasticamente o risco de alucinações (pois o LLM teria que recuperar fatos e estilizá-los na mesma passagem sem validação intermediária de grounding), e eliminaria a especialização do `Personality Agent` como camada de compliance e tom de voz centralizada.
  - *Opção Escolhida*: Manter a orquestração limpa e desacoplada em 3 agentes especializados e calibrar o SLO do Fast Path para **7.000 ms**.
  - *Mitigação de UX*: A percepção de espera do lojista é totalmente resolvida pelo **Streaming SSE com digitação em tempo real** implementado na Task 7.2. Como o Time to First Token (TTFT) é de $\le 1.000\text{ ms}$, o usuário vê o texto fluindo imediatamente na tela, eliminando a ansiedade de espera, enquanto o sistema opera de forma segura, modular e auditável.

- **[Risk] DuckDuckGo Rate-Limiting on Institutional/General Queries** → **Mitigation**: Upgrade to the `ddgs` package and add a zero-key **Wikipedia REST API (`pt.wikipedia.org` / `en.wikipedia.org`)** search enrichment inside `web_search_general` for historical/institutional queries, ensuring real factual retrieval even if DuckDuckGo rate-limits container IPs.
