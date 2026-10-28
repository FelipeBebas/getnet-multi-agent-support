# Tasks

## 1. Zero-Mockup Authenticity, Automatic Local Timezone & Dynamic Corrective Web Search

- [x] 1.1 Fix automatic local timezone resolution in `src/tools/knowledge_tools.py` using `timezone=auto` in Open-Meteo and `datetime.now().astimezone()` (instead of `timezone.utc`) so `"tomorrow"` and `"today"` automatically match the user's and target city's UTC offset, and verify via unit tests in `tests/unit/test_tools.py`
- [x] 1.2 Remove hardcoded fallback templates ("Zero Maquiagem") across `src/agents/knowledge_agent.py`, `src/tools/knowledge_tools.py`, and `src/rag/vector_store.py`: enable real `OpenAIEmbeddings` (`text-embedding-3-small`) when `OPENAI_API_KEY` is present, remove the artificial `max(0.65, ...)` confidence floor so low-confidence queries genuinely trigger fallback or human escalation (`< 0.60`), and prevent canned English product paragraphs from being returned on low-similarity queries
- [x] 1.3 Implement dynamic Corrective RAG-to-Web-Search fallback in `src/agents/router_agent.py`, `src/agents/knowledge_agent.py`, and `src/tools/knowledge_tools.py`: without pre-saving out-of-scope answers in the RAG corpus, ensure that whenever a query is not answered by the retrieved RAG chunks (low similarity or semantic mismatch, such as `"Quando a getnet foi inaugurada?"`), the agent discards irrelevant RAG chunks and dynamically invokes `web_search_general` to search the live internet and return the real answer in the user's language

## 2. LangSmith Metrics, Experiments & Automated Evals

- [x] 2.1 Upgrade `scripts/evaluate.py` and `src/observability/tracer.py` to integrate `langsmith.evaluation.evaluate` with 4 custom evaluators (`routing_accuracy`, `tool_accuracy`, `rubric_groundedness`, and `llm_faithfulness_judge`) plus token/latency metrics, and expose `POST /evals/run` in `src/api/routes.py` so evaluation experiments and scorecards can be triggered and inspected directly inside the LangSmith web UI (not only via Swagger/CLI)

## 3. Hierarchical Tree (DAG) Dashboard & Custom System Design

- [x] 3.1 Refactor the orchestration visualization in `src/api/dashboard.py` (`GET /dashboard`) from a flat horizontal queue of boxes into a **Hierarchical Tree / DAG Visualization** (`Input Guardrail` → `Router Agent` → branching to `Knowledge Agent`, `Customer Support Agent`, and `Escalation Agent` with their child Tool nodes → converging into `Personality Agent` → `Output Guardrail`) with real-time branch highlighting, and verify `GET /dashboard` renders the tree structure in `pytest tests/integration/test_api_endpoints.py`
- [x] 3.2 Apply the user's custom System Design to `src/api/dashboard.py` (`GET /dashboard`) once the visual design specification is provided (left open for user design input)

## 4. Dashboard Refinements, Brand Identity & Routing Robustness

- [x] 4.1 Header, Brand Identity & DX Navigation:
  - Inserir logo vetorial/SVG da Getnet no header (Item 13)
  - Substituir badge "Service Healthy" por badge dinâmico do modelo ativo (`● Model: gpt-4o-mini` / `mock` via `/health`) (Item 1)
  - Adicionar botão de navegação direta para Swagger API Docs (`/docs`) em nova aba (Item 16)
  - Adicionar botão de navegação direta para o projeto no LangSmith UI (Item 15)
- [x] 4.2 Console de Entrada & Loader Snake 3x3 Getnet:
  - Travar campo `Merchant User ID` como `readonly` (Item 2)
  - Isolar `Query Message`, textarea e botão `Run scenario` em card destacado de alta visibilidade (Item 3)
  - Implementar loader animado com a matriz 3x3 de quadrados vermelhos da Getnet em percurso estilo snake durante execução para eliminar sensação de tela congelada (Item 17)
- [x] 4.3 Árvore de Fluxo, Grid de Fundo & Papeis dos Agentes:
  - Estilizar Input e Output Guardrails distintamente como Gateways de Segurança com ícones SVG dedicados (Item 4)
  - Adicionar grid sutil de pontos (dot pattern) perfeitamente espaçados em tom cinza suave no fundo do canvas da árvore (Item 10)
  - Implementar animações vibrantes de fluxo e partículas luminosas ativas nos caminhos e nós do grafo (Item 8)
  - Ajustar rotulação dos agentes na árvore e no badge para explicitar o bônus e a síntese: `Agent 1: Router Agent`, `Agent 2: Knowledge Agent`, `Agent 3: Customer Support Agent`, `Agent 4 (Bonus Agent): Human Escalation Agent` e `Agent 5 (Synthesis Layer): Personality Agent` (Item 5)
- [x] 4.4 Arquitetura Anti-Frágil: RAG Sem Falsos Positivos, Busca Web Delimitada & Roteamento Robusto:
  - Remover bônus artificial de clusters para frases genéricas (ex: `"difference between"` e `"diferença entre"`) em `src/rag/vector_store.py` e implementar verificação estrita de cobertura de entidades (Entity Coverage Check) em `src/agents/knowledge_agent.py` para detectar produtos inexistentes (ex: `"Get Bronze Water"`) sem inflar similaridade
  - Delimitar busca web ao domínio oficial da Getnet (`site:site.getnet.com.br` ou termo obrigatório `"Getnet"`) em `src/tools/knowledge_tools.py` e implementar filtro de Citações Atribuídas (Attributed Citations Gate), garantindo que apenas fontes que realmente embasaram a resposta entrem no array `sources` (eliminando links de Wikipédia/Aristóteles, blogs de torneiras e YouTube)
  - Criar intenção explícita `out_of_scope` / `unrecognized` no `src/agents/router_agent.py` com resposta orientativa educada para ruídos (ex: `"123 teste block"`), impedindo que caiam no RAG por default e evitando abertura indevida de chamados humanos no `escalation_agent`
  - Capturar e agregar o `token_usage` real da OpenAI (`response_metadata`) em todos os agentes (`router`, `knowledge`, `support`, `personality`) nos spans de telemetria para que `total_tokens` reflita com precisão o consumo do modelo
  - Eliminar concatenações brutas de markdown repetido (`## POS Terminal Comparison...`) nos fallbacks offline de `knowledge_agent.py` e `personality_agent.py`
  - Corrigir renderização de `Sources & Grounding References` no frontend do dashboard: formatar como links clicáveis apenas URLs `http(s)://` válidas e exibir tags internas como badges (Item 9)
- [x] 4.5 Inspetores Abertos, Gráfico de Telemetria da Sessão & Rodapé:
  - Definir sanfonas de inspeção (`Inspect response JSON` e `Inspect raw telemetry`) abertas por padrão (`open`) (Item 11)
  - Adicionar gráfico de histórico da sessão na seção de telemetria medindo latência e volume por requisição (Item 12)
  - Adicionar rodapé profissional com credenciais do autor, links de portfólio/GitHub e nota de arquitetura (Item 14)

## 5. Multi-Turn Session Memory, Contextual Query Rewriter & Conversational Anti-Fragility

- [x] 5.1 In-Memory Multi-Turn Session Store:
  - Implementar gerenciador de histórico conversacional em memória (`SessionStore`) indexado por `user_id` (ex: `cliente1988`), retendo os últimos turnos `{"role": "user"|"assistant", "content": str, "timestamp": str}`
  - Propagar `chat_history` no `OrchestrationState` e integrar aos nós de execução do LangGraph em `src/orchestration/graph.py`
  - Expor endpoint para inspecionar ou limpar a memória da sessão (`DELETE /chat/history/{user_id}`)
- [x] 5.2 Contextual Query Rewriter & Desambiguação de Follow-up:
  - Adicionar camada de reescrita contextual (Contextual Query Rewriting) no `src/agents/router_agent.py`: quando a mensagem for elíptica/dependente de contexto (ex: `"what about yen?"`, `"e no débito?"`, `"quanto custa ela?"`), usar o histórico recente para desambiguar e sintetizar a query canônica auto-contida antes do roteamento, busca vetorial no RAG ou acionamento de ferramentas
  - Alimentar os prompts de sistema do `KnowledgeAgent`, `CustomerSupportAgent` e `PersonalityAgent` com as mensagens anteriores para manter coerência dialógica
- [x] 5.3 Resiliência de Ferramentas Web e Câmbio Multi-Moeda:
  - Corrigir a variável `verified_hits` -> `valid_hits` na verificação de fontes de `src/tools/knowledge_tools.py` para prevenir falhas fatais (HTTP 500) em caso de buscas sem retorno ou timeouts de rede
  - Expandir o detector e buscador de câmbio (`_fetch_exchange_rate`) para suportar moedas globais chave (EUR, USD, JPY, GBP) com taxas dinâmicas e fallback offline contextualizado
  - Adicionar guardrail defensivo no frontend do dashboard (`src/api/dashboard.py`) com verificação `if (!res.ok)` para interceptar erros HTTP de rede com feedback amigável
- [x] 5.4 Testes de Regressão e Encadeamento Conversacional:
  - Criar testes unitários em `tests/unit/test_session_memory.py` validando o acúmulo de turnos na sessão e a reescrita de perguntas elípticas
  - Adicionar testes de integração em `tests/integration/test_multi_turn_chat.py` simulando sequências de perguntas encadeadas (ex: Euro -> Yen, Get Clássica -> taxas/aluguel) sem quebra de contexto

## 6. Anti-Hallucination Grounding, Calibrated Confidence & Dynamic Human Escalation (Hardcore AI Resilience)

- [x] 6.1 Contrato Estrito de Grounding (Anti-Hallucination Prompting) no `src/agents/knowledge_agent.py`:
  - Impor regra estrita de *Direct Entailment* no `KNOWLEDGE_SYSTEM_PROMPT`: se datas específicas, nomes ou fatos não constarem de forma literal e explícita nos trechos (chunks ou busca web), proibir terminantemente o modelo de extrapolar, deduzir ou juntar fragmentos desconexos para formar fatos inventados.
  - Exigir que o modelo declare com precisão o que foi e o que não foi encontrado nos registros consultados.
- [x] 6.2 Calibração de Confiança Baseada em Evidência (Evidence-Based Calibration) no `src/agents/knowledge_agent.py`:
  - Remover a atribuição fixa e artificial de `confidence = 0.88` quando a busca web é acionada por Corrective RAG.
  - Avaliar a suficiência factual dos resultados da busca web: se a informação exata não for comprovada ou o modelo indicar incerteza, calibrar a confiança para `< 0.60` (ex: `0.45`), refletindo o estado epistêmico real do sistema.
- [x] 6.3 Handoff Gracioso e Acionamento Nativo do `Agent 4 (Human Escalation)` no `src/orchestration/graph.py` e `personality_agent.py`:
  - Garantir que quando `confidence < 0.60` em consultas de conhecimento com dados incompletos, o LangGraph transite organicamente para o `escalation_agent`, executando a ferramenta `dispatch_human_handoff` e gerando protocolo de atendimento.
  - Garantir que o `Personality Agent` preserve a postura de transparência corporativa, comunicando que o tema foge da documentação técnica pública e que o cliente está sendo transferido para um operador humano.
- [x] 6.4 Testes de Red-Teaming & Validação de Não-Regressão:
  - Adicionar teste unitário de Red-Teaming em `tests/unit/test_router.py` / `tests/unit/test_knowledge_grounding.py` simulando perguntas históricas ou fora de escopo (ex: fundação, fatos de 2005), verificando que o sistema não alucina, calibra confiança `< 0.60` e aciona o `escalation_agent`.
  - Executar a suíte de testes de integração (`test_challenge_scenarios.py` e `test_api_endpoints.py`) para assegurar que nenhum dos cenários oficiais do desafio sofreu regressão.

## 7. Dynamic Multi-Tier SLO Calibration & Real-Time Token Streaming (SRE Production Readiness)

- [x] 7.1 Calibração de SLO Dinâmico e Segmentado por Complexidade de Rota (Multi-Tier SLO):
  - No `src/config/settings.py` e `src/observability/tracer.py`, substituir o limiar único e estático de latência por um modelo multi-tier sensível à complexidade da rota:
    - `Fast Path SLO` (RAG local, FAQs, Guardrail Blocks, POS Diagnostics): $\le$ 4.000 ms.
    - `Deep Research / Corrective RAG SLO` (busca web externa via DuckDuckGo/Tavily, multi-agente serial com re-síntese e handoff humano): $\le$ 18.000 ms.
  - Avaliar o gatilho `HIGH_LATENCY_ALERT` com base no `effective_slo_target_ms` dinâmico da rota executada, eliminando falsos positivos na telemetria.
  - Propagar `effective_slo_target_ms` e `slo_status` no payload da API e refletir no gráfico de histórico (`Session Execution History`) e tooltips do dashboard em `src/api/dashboard.py`.
- [x] 7.2 Streaming de Tokens em Tempo Real (Server-Sent Events / SSE) & Efeito de Digitação:
  - Implementar endpoint `POST /chat/stream` usando `StreamingResponse` com padrão SSE (`text/event-stream`), transmitindo eventos progressivos de ciclo de vida (`node_started`, `node_completed`, `token`, `final_result`).
  - Habilitar streaming assíncrono de tokens no `PersonalityAgent` (`astream`) para que o Time to First Token (TTFT) caia para $\le$ 1.000 ms.
  - Atualizar a interface do dashboard em `src/api/dashboard.py` para consumir o stream via `EventSource` / `fetch(ReadableStream)`, renderizando os tokens dinamicamente no `Live Execution Result` conforme são gerados.
- [x] 7.3 Testes Automatizados de SLO Dinâmico e Streaming SSE:
  - Criar testes unitários em `tests/unit/test_observability.py` validando os tiers de SLO e ausência de falsos alertas para buscas externas.
  - Adicionar testes de integração em `tests/integration/test_api_endpoints.py` validando o stream contínuo de tokens e eventos SSE.
  - Executar validação de não-regressão em toda a suíte.

## 8. Calibração Realista do Fast Path SLO (7.000ms) & Refinamento Visual do Gráfico (Trade-off SRE)

- [x] 8.1 Calibrar Fast Path SLO para 7.000ms e Atualizar Gráfico do Dashboard:
  - No `src/config/settings.py` e `src/observability/tracer.py`, atualizar o limiar de `latency_slo_fast_path_ms` para `7000.0` ms, refletindo a física real do pipeline de 3 agentes seriais (`Router` → `Knowledge` → `Personality` via `gpt-4o-mini`).
  - No `src/api/dashboard.py`, atualizar a linha de referência do Fast SLO para `Fast SLO (7.000ms)` / `7000ms`, ajustar o espaçamento das etiquetas SVG para evitar colisão visual com os valores das barras (ex: rótulo colidindo em `#7`), e atualizar os chips e tooltips.
  - Atualizar testes automatizados em `tests/unit/test_observability.py` e `tests/integration/test_api_endpoints.py` para validar a nova calibragem de 7.000ms.

## Workflow follow-up

- Run `openspec validate "authentic-rag-langsmith-and-tree-dashboard" --strict` to verify all delta specs and planning artifacts remain valid.
- Archive the change (`openspec archive "authentic-rag-langsmith-and-tree-dashboard"`) after all tasks (including the custom Dashboard System Design in 3.2) are implemented and verified.
