# 🎬 Roteiro Oficial de Apresentação (15 Minutos)
## Getnet Multi-Agent Customer Support System
**Apresentador:** Felipe  
**Papel:** Staff AI Engineer  
**Objetivo:** Demonstração técnica de alta fidelidade defendendo a submissão do desafio `AI_Hardcore_Engineer_Multi-Agent.md`.

---

## 🧭 Preparação de Telas Antes de Apertar o REC
Tenha 4 janelas/abas prontas para alternar de forma limpa:
1. **Aba 1 (Navegador):** `http://localhost:8000/dashboard` (com o container Docker já rodando).
2. **Aba 2 (VS Code):** O projeto aberto com o `README.md` renderizado e as pastas `src/` visíveis.
3. **Aba 3 (Terminal PowerShell):** Na raiz do projeto, pronto para rodar `python scripts/evaluate.py`.
4. **Aba 4 (PDF/Markdown):** O documento do briefing `AI_Hardcore_Engineer_Multi-Agent.md`.

---

## 🗺️ Matriz de Mapeamento: Briefing x Minutos do Vídeo

| Bloco | Minutagem | Seção do Briefing (`.md`) | Requisito Exato Comprovado | O que Mostrar na Tela |
| :--- | :--- | :--- | :--- | :--- |
| **Camada 1** | 00:00 - 03:00 | **The Task & Core Req 1** | • Spec-Driven Development (OpenSpec)<br>• Regra de 60 min de Core<br>• Arquitetura Multi-Agente (LangGraph) | Diagrama Mermaid do `README.md` e arquivo `src/orchestration/graph.py` |
| **Camada 2** | 03:00 - 06:00 | **Core Req 1 (Agent 2)** | • Knowledge Agent<br>• RAG em 3 Camadas (ChromaDB)<br>• Web Search Tool & Anti-Alucinação | `src/rag/ingest.py`, `src/rag/vector_store.py` e Dashboard com Cenários 1, 2 e 3 |
| **Camada 3** | 06:00 - 09:00 | **Core Req 1 (Agent 3) & Core Req 2** | • Customer Support Agent (3 Ferramentas)<br>• Telemetria POS & ISO-8583 (Erro 51)<br>• API FastAPI POST com JSON | `src/tools/support_tools.py`, `data/merchants.json` e chamada `/chat` no Dashboard |
| **Camada 4** | 09:00 - 12:00 | **Bonus Challenges** | • 4º Agente (Human Escalation)<br>• Guardrails Bidirecionais (PCI/LGPD/Injection)<br>• Observabilidade, Traces & Dashboard | Dashboard bloqueando Prompt Injection, máscara de cartão e `/alerts` |
| **Camada 5** | 12:00 - 15:00 | **Core Req 3, 4 & 10 Cenários** | • Pirâmide de Testes (80 testes no pytest)<br>• Benchmark ao vivo (10/10 cenários do briefing)<br>• Dockerfile, docker-compose & Encerramento | Terminal rodando `python scripts/evaluate.py` e `docker-compose.yml` |

---

## 🟢 Camada 1: Apresentação, SDD (OpenSpec) & Arquitetura Multi-Agente (00:00 - 03:00)

### 🖥️ O que mostrar na tela:
- Inicie na Aba 4 mostrando o cabeçalho do briefing (`AI_Hardcore_Engineer_Multi-Agent.md`).
- Alterne para a Aba 2 (VS Code) exibindo o diagrama Mermaid no `README.md` e o arquivo `src/orchestration/graph.py`.

### 🎙️ O que falar:
> *"Olá a todos os avaliadores técnicos da Getnet. Meu nome é Felipe e hoje apresento o **Getnet Multi-Agent Customer Support System**, desenvolvido para atender integralmente ao desafio de Staff AI Engineer.
>
> O briefing define um desafio claro: construir uma orquestração multi-agente utilizando **Spec-Driven Development (SDD)** e com um limite estrito de **60 minutos de desenvolvimento para a solução core**.
>
> Para atender a essa premissa com rigor de engenharia, decidi estruturar todo o sistema através do **OpenSpec**. Diferente de frameworks de especificação como o SpecKit — que muitas vezes se tornam excessivamente verbosos, engessados e burocráticos —, o OpenSpec nos permite definir contratos de software objetivos baseados nas cláusulas formais **SHALL**, **WHEN** e **WHERE** (padronizadas pela RFC-2119). 
>
> Graças a essa disciplina de SDD, os esquemas de estado, os contratos de entrada e saída das ferramentas e a máquina de transições foram especificados antes de qualquer linha de código. Isso nos permitiu ter o **core funcional da orquestração concluído em menos de 60 minutos**, reservando o tempo restante para o que realmente transforma um protótipo em software de produção: testes de integração, observabilidade avançada e guardrails de segurança."*

### ❓ Trade-off / Pergunta da Banca Respondida ao Vivo:
> *"Por que escolhemos o **LangGraph** em vez de frameworks como CrewAI, AutoGen ou uma simples cadeia linear de prompts?
> No ecossistema financeiro de adquirência, lidamos com dinheiro, liquidação de recebíveis e terminais POS. Um framework conversacional puramente probabilístico (como CrewAI) pode alucinar ciclos infinitos ou desvios de rota. O LangGraph trata a orquestração como um **Grafo Direcionado de Estados (StateGraph)** fortemente tipado através de `OrchestrationState`. Isso nos dá roteamento determinístico, tratamento de memória transacional e interrupção imediata em caso de violação de segurança.
>
> Em vez dos 3 agentes mínimos solicitados pelo edital, implementamos **5 agentes especializados**:
> 1. **Router Agent**: ponto de entrada e classificador de intenções.
> 2. **Knowledge Agent**: especialista em produtos Getnet com RAG e Web Search.
> 3. **Customer Support Agent**: suporte técnico com ferramentas de extrato e telemetria.
> 4. **Human Escalation Agent**: para clientes insatisfeitos ou dúvidas de baixa confiança.
> 5. **Personality Agent**: desacoplamos a voz da marca da lógica de domínio para garantir empatia, síntese e streaming token a token sem poluir os agentes especialistas."*

---

## 🔵 Camada 2: RAG Pipeline, Grounding & Web Search (03:00 - 06:00)

### 🖥️ O que mostrar na tela:
- Arquivo `src/rag/ingest.py` (citar BeautifulSoup e URLs da Getnet).
- Arquivo `src/rag/vector_store.py` (citar ChromaDB e `GetnetHybridEmbeddingFunction`).
- Abrir a Aba 1 (Dashboard) e disparar o **Cenário 1** (*"When was Getnet founded?"*) e **Cenário 2** (*"Difference between Get Clássica and Get Smart"*).

### 🎙️ O que falar:
> *"Passando para a Seção Core Requirements do briefing, o documento exige o **Agent 2 (Knowledge Agent)**: um agente capaz de responder sobre os produtos e serviços da Getnet ancorado no site oficial, combinando RAG com uma ferramenta de busca web para perguntas gerais.
>
> Arquitetamos um pipeline de RAG industrial dividido em 3 camadas:
> 1. **Ingestão & Corpus (`src/rag/ingest.py`):** Criamos um web scraper limpo com BeautifulSoup que varre as URLs solicitadas no briefing (`getnet.net/en`, `maquininhas`, `link-de-pagamento` e `dúvidas`). O texto é fatiado em `DocumentChunks` de 512 tokens com sobreposição de janela (*sliding window*) de 64 tokens, preservando metadados de proveniência (`source_url`, títulos e tags).
> 2. **Armazenamento Vetorial Persistente (`src/rag/vector_store.py`):** Utilizamos o **ChromaDB persistente** com indexação HNSW baseada em distância de cosseno. Para evitar qualquer fragilidade em ambientes de build ou falta de internet, criamos a `GetnetHybridEmbeddingFunction`. Ela combina vetores de conceitos do ecossistema de pagamentos com n-grams locais, permitindo buscas semânticas determinísticas offline e com fallback resiliente para OpenAI Embeddings.
> 3. **Camada de Recuperação & Anti-Alucinação (`Direct Entailment Contract`):** Se a busca no banco vetorial identificar que a pergunta exige fatos externos não contidos no corpus (como previsão do tempo ou cotação de moedas), o Knowledge Agent aciona a ferramenta `web_search_duckduckgo` em `src/tools/knowledge_tools.py`."*

### ❓ Trade-off / Pergunta da Banca Respondida ao Vivo:
> *"Como garantimos que o Knowledge Agent não alucina taxas ou anos inventados?
> Aplicamos um contrato rigoroso de **Direct Entailment**: se um fato específico não estiver presente no contexto recuperado, o agente é proibido de especular. Ele emite a tag `[INSUFFICIENT_EVIDENCE]`, que reduz a confiança e aciona o handoff humano. 
> 
> Além disso, criamos um teste para produtos inexistentes como o 'Get Bronze Water': o sistema detecta que a entidade não pertence ao catálogo Getnet, informa categoricamente que o produto não existe e apresenta a linha oficial com os 5 modelos: Get Tap, Get Mini, Get Lite, Get Clássica e Get Smart.
> 
> Como vemos no Dashboard, comprovamos os cenários do briefing: o **Cenário 1** cita a fundação da Getnet em 2003 no Rio Grande do Sul e a aquisição pelo Santander; o **Cenário 2** detalha a diferença de teclado físico versus tela Android da Smart; e o **Cenário 3** confirma o crediário em até 48 vezes com liquidação em D+2."*

---

## 🟣 Camada 3: Customer Support Agent, Telemetria POS & APIs (06:00 - 09:00)

### 🖥️ O que mostrar na tela:
- Arquivo `src/tools/support_tools.py` (mostrar as 3 funções de ferramentas).
- Arquivo `data/merchants.json` (mostrar a estrutura do `cliente1988`).
- Dashboard: Clicar nos chips do **Cenário 4** (*"When will yesterday's money be deposited?"*) e **Cenário 5** (*"Card machine won't connect to internet"*).

### 🎙️ O que falar:
> *"O briefing exige para o **Agent 3 (Customer Support Agent)** a recuperação de dados reais do usuário e a criação de **pelo menos 2 ferramentas**, além de um endpoint HTTP `POST /chat` em FastAPI recebendo o JSON com `message` e `user_id`.
> 
> Nós fomos além e desenvolvemos **3 ferramentas completas de produção** em `src/tools/support_tools.py`:
> 1. `get_merchant_settlement_status`: Consulta a câmara de liquidação financeira do lojista.
> 2. `diagnose_pos_and_transactions`: Inspeciona a telemetria de conectividade da máquina e o switch de autorização de transações.
> 3. `manage_support_ticket`: Abertura e acompanhamento de chamados técnicos com SLA.
> 
> Para validar esses cenários, modelamos o **`cliente1988`** (`data/merchants.json`). Ele representa a Padaria & Café Bela Vista Ltda, de Porto Alegre, operando uma maquininha Get Smart no plano 'Receba Já D+1'.
> 
> Vejam no Dashboard o **Cenário 4**: o lojista pergunta quando cairá o dinheiro das vendas de ontem. O agente aciona a ferramenta de extrato e responde com precisão contábil: *'Ontem foram registradas 64 transações totalizando R$ 4.850,00 brutos (R$ 4.712,25 líquidos), com depósito agendado para hoje entre 09:00 e 14:30 na sua conta corrente Santander agência 3421'*."*

### ❓ Trade-off / Pergunta da Banca Respondida ao Vivo:
> *"Como provamos que a falha de conectividade e o erro de transação são reais de mercado?
> No **Cenário 5**, o lojista diz que a máquina não conecta na internet. Nossa ferramenta de telemetria identifica que a máquina Get Smart estava tentando conectar na rede Wi-Fi na faixa de 5GHz. Como muitos terminais POS Android suportam prioritariamente a banda de 2.4GHz b/g/n, o agente guia o lojista a conectar no Wi-Fi 2.4GHz ou reiniciar o modem.
> 
> E no **Cenário 6**, o lojista relata erro de transação recusada na maquininha. O sistema consulta o histórico recente e identifica o **Código 51 do padrão ISO-8583**. 
> Para a banca examinadora: o padrão **ISO-8583** é a norma técnica bancária mundial utilizada por todas as adquirentes e bandeiras (Mastercard, Visa, Getnet, Santander). O Código 51 significa universalmente **'Not Sufficient Funds / Insufficient Funds' (Saldo ou Limite Insuficiente)**. O agente tranquiliza o comerciante explicando que a máquina está perfeita e que o motivo foi falta de limite no cartão do cliente, sugerindo tentar no débito ou gerar um Pix QR Code na tela da Get Smart.
> 
> Também resolvemos o desafio de **Multi-Turn Contextual**: se o cliente perguntar em seguida 'quanto custa a bobina dela?', nosso `Contextual Query Rewriter` resgata o histórico da sessão e explica que o modelo Smart emite comprovante digital por SMS ou e-mail, mantendo a coerência conversacional."*

---

## 🟠 Camada 4: Bonus Challenges (Segurança, Guardrails & Observabilidade) (09:00 - 12:00)

### 🖥️ O que mostrar na tela:
- Arquivo `src/guardrails/validator.py`.
- Dashboard: Clicar no chip do **Cenário 8** (*"Prompt Injection Attack"*). Mostrar o badge vermelho **BLOCKED (Security Guardrail)**.
- Alterne para a aba de auditoria ou faça uma chamada a `GET /alerts`.

### 🎙️ O que falar:
> *"O briefing inclui uma seção dedicada de **Bonus Challenges**: adicionar um 4º agente (Human Escalation), implementar guardrails de segurança, handoff humano em caso de baixa confiança e estratégia de observabilidade com dashboards e alertas. Cobrimos 100% dos bônus.
> 
> Em sistemas financeiros, a segurança deve operar em duas fronteiras:
> 1. **Ingress Guardrail (Proteção de Entrada):** Intercepta o payload antes de qualquer LLM ser acionada. Ele neutraliza ataques de Prompt Injection (como 'Ignore all previous instructions', 'Jailbreak', 'System override') e comandos maliciosos de fraude na borda (*edge*) em menos de 1 milissegundo, bloqueando o ataque sem gastar tokens e gerando um alerta de segurança imediato.
> 2. **Egress Guardrail (Proteção de Saída):** Aplica conformidade regulatória estrita com **PCI-DSS** e **LGPD**. Toda resposta passa por uma sanitização ativa que mascara números de cartões de 16 dígitos com `[PCI_PAN_MASKED]` e documentos pessoais com `[LGPD_CPF_MASKED]`, garantindo que dados sensíveis nunca vazem para o cliente final."*

### ❓ Trade-off / Pergunta da Banca Respondida ao Vivo:
> *"Como tratamos o 4º Agente e a Observabilidade em Produção?
> Implementamos o **Agent 4 (Human Escalation Agent)**. Ele entra em ação em dois momentos críticos:
> 1. Quando o usuário demonstra sentimento agressivo ou ameaça de churn (ex: 'Vou cancelar a máquina e processar a Getnet').
> 2. Quando o score de confiança do modelo cai abaixo do limiar de 60%. O agente gera um ticket de prioridade alta com o resumo estruturado da conversa, liberando o lojista para falar com um operador humano.
> 
> Para a observabilidade, integramos **Logs Estruturados em JSON via structlog**, traces distribuídos compatíveis com **LangSmith** e **Langfuse**, e um **Engine de SLO Dinâmico Multi-Tier**:
> - **Fast Path (≤ 7s):** Para consultas de RAG local e diagnósticos internos.
> - **Complex Path (≤ 18s):** Para buscas web ao vivo na internet.
> Se qualquer requisição ultrapassar esse limiar, a rota `/alerts` sinaliza a degradação de performance para o time de SRE."*

---

## 🔴 Camada 5: Suíte de Testes, Benchmark dos 10 Cenários & Docker (12:00 - 15:00)

### 🖥️ O que mostrar na tela:
- Terminal na Aba 3 executando: `python scripts/evaluate.py`.
- Arquivo `Dockerfile` e `docker-compose.yml`.
- Mostrar a tabela verde do terminal com 10/10 cenários passando.

### 🎙️ O que falar:
> *"Na seção 'What We're Looking For' e no Requisito 4, o briefing enfatiza a necessidade de testes eficazes, qualidade de código e facilidade de deploy.
> 
> Construímos uma pirâmide de testes sólida:
> - **80 testes automatizados no pytest:** cobrindo 100% dos guardrails, vetores do ChromaDB, roteamento dos agentes e contratos da API FastAPI.
> - **Benchmark Automatizado (`scripts/evaluate.py`):** Criamos uma suíte de avaliação formal que executa os 10 cenários de teste listados no briefing contra o nosso dataset de ground-truth (`data/eval_dataset.json`).
> 
> Vejam agora o terminal ao vivo rodando a avaliação:
> *(Aponte para a tabela no terminal)*
> Os resultados são conclusivos:
> - **10 de 10 Cenários Oficiais Aprovados (100% de Sucesso);**
> - **100% de Acurácia de Roteamento (Routing Accuracy);**
> - **100% de Seleção Correta de Ferramentas (Tool Selection Accuracy);**
> - **100% de Groundedness Semântico nas Respostas.**
> 
> Para o Requisito 3 (Dockerization), toda a aplicação está empacotada em um `Dockerfile` multi-estágio em Python 3.12-slim. O build pré-popula a base do ChromaDB para garantir que o container inicialize em segundos com zero dependência externa. Basta executar `docker compose up -d` e o serviço estará rodando com healthcheck ativo na porta 8000."*

### ❓ Pergunta Final da Banca: Como escalar para 50.000 requisições/minuto?
> *"Se este sistema for submetido a um volume massivo de 50.000 requisições por minuto:
> 1. **Sessão:** Migraríamos o `SessionStore` (atualmente em memória com lock assíncrono) para um cluster **Redis** ou **DynamoDB** com expiração TTL por lojista.
> 2. **Filas Assíncronas:** Inseriríamos **RabbitMQ** ou **Apache Kafka** na frente das tarefas pesadas de Web Search e RAG, com workers distribuídos via Celery ou Temporal.
> 3. **Cache Semântico:** Implementaríamos **Redis Semantic Cache** para perguntas com alto volume de repetição sobre produtos (ex: diferença entre Smart e Clássica), cortando até 70% das chamadas a LLM.
> 4. **Vector Store:** Escalaríamos o ChromaDB para uma instância distribuída em cluster como Qdrant ou pgvector na nuvem Santander/Getnet."*

### 🏁 Encerramento (Últimos 30 segundos):
> *"Com isso, cobrimos com nota máxima todos os Requisitos Obrigatórios, os Desafios Bônus e os 10 Cenários do briefing `AI_Hardcore_Engineer_Multi-Agent.md`. O repositório no GitHub conta com o `README.md` completo, documentação de arquitetura e instruções de build.
> 
> Muito obrigado pela oportunidade e estou à disposição para aprofundarmos em qualquer detalhe técnico!"*

---

## 📋 Checklist Final para a Gravação
- [ ] Docker iniciado (`docker compose up -d`) e dashboard aberto em `http://localhost:8000/dashboard`.
- [ ] Terminal com o comando preparado: `python scripts/evaluate.py`.
- [ ] VS Code com o `README.md` aberto e diagrama Mermaid visível.
- [ ] Tempo cronometrado entre 13 e 15 minutos (nunca ultrapassar 15:00).
- [ ] Ao terminar, subir o vídeo no YouTube (como Não Listado) ou Google Drive e colar o link na linha 14 do `README.md`.
