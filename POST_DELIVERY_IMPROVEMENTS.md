# 📑 Post-Delivery Architectural Analysis & SDD Delta
## Getnet Multi-Agent Customer Support System
**Data:** 28 de Outubro de 2026 (Atualizado em 29 de Outubro de 2026)  
**Autor:** Felipe (Staff AI Engineer)  
**Status:** ✅ Implementado e Validado via OpenSpec (`escalation-gating-by-risk-tier`)  

---

### 1. 🔍 O Incidente / Ponto de Atenção Identificado

#### Cenário:
Durante os testes de validação ao vivo com a pergunta *"When was Getnet founded?"*, o sistema respondeu corretamente que a empresa foi fundada em 2003 no Rio Grande do Sul e adquirida pelo Santander em 2014, mas **derrubou a confiança para 0.45 e acionou o Agente de Escalada Humana**, abrindo um ticket de suporte prioritário (`TCK-2026-...`) e protocolo na Mesa de Risco Nível 2.

#### Impacto de Negócio (Business & Operations):
No mundo corporativo real, abrir um chamado humano e enfileirar um operador com SLA de 2 minutos para validar uma curiosidade enciclopédica/histórica que o próprio bot já respondeu gera:
1. **Aumento artificial do Custo por Contato (CPC / AHT);**
2. **Fila desnecessária na equipe humana**, tirando o foco de lojistas com maquininhas travadas ou contestações de chargeback;
3. **Experiência confusa para o lojista**, que recebe um protocolo de suporte sem ter solicitado suporte humano.

---

### 2. 🧠 Root Cause Analysis (RCA) na Especificação (SDD)

Por que o Spec-Driven Development (SDD) original não preveniu isso?

1. **Acoplamento Indiscriminado de Incerteza à Escalada:**
   A especificação inicial definia a seguinte regra genérica:
   > *"IF epistemic_uncertainty == TRUE OR confidence < 0.60 THEN trigger escalation_agent."*
2. **Ausência de Matriz de Risco de Negócio (Risk Tiering):**
   A regra de escalada tratava todas as incertezas com o mesmo peso. O sistema não distinguia:
   - **Incerteza de Alto Risco Financeiro/Operacional:** Erro em transação de R$ 5.000, máquina sem sinal no caixa, contestação de fraude (onde a escalada humana é **obrigatória**).
   - **Incerteza de Baixo Risco / Domínio Público:** Curiosidades sobre o ano de fundação, cotação de moedas ou previsão do tempo (onde a escalada humana é um **desperdício de recursos**).

---

### 3. 📐 Proposta de Ajuste na Especificação (SDD Delta Contract)

A nova especificação formal deve desacoplar a incerteza estatística da ação de abertura de chamados, introduzindo a cláusula formal:

```markdown
### SPEC DELTA: Escalation Gating by Business Risk Tier

1. [RISK-CLASSIFICATION]
   WHEN an incoming message or dialogue turn is evaluated, the Router Agent 
   SHALL assign a Risk Tier:
   - CRITICAL / HIGH: Chargeback, fraud dispute, churn threat, transaction settlement discrepancy, hardware failure.
   - MEDIUM: POS configuration issues, fee inquiries, account registration updates.
   - LOW / INFORMATIONAL: General product specifications, public corporate history, weather, currency exchange, greetings.

2. [CONDITIONAL-ESCALATION-GATE]
   WHEN confidence_score < CONFIDENCE_THRESHOLD (0.60):
   - The Orchestrator SHALL trigger Agent 4 (Human Escalation) ONLY IF Risk Tier in (CRITICAL, HIGH, MEDIUM).
   - IF Risk Tier is LOW / INFORMATIONAL, the system SHALL output the best-effort answer with epistemic caveats, 
     SHALL NOT create support tickets, and SHALL NOT enqueue human specialists.
```

---

### 4. 🛠️ Plano de Implementação no Código (Pós-Vídeo)

1. **No arquivo `src/orchestration/state.py`:**
   Adicionar o campo `risk_tier: Literal["high", "medium", "low"] = "low"` no `RouterPlan` e `OrchestrationState`.

2. **No arquivo `src/orchestration/graph.py`:**
   Refinar a função `_dispatch_next_from_queue`:
   ```python
   # Escalada automática condicionada ao risco do negócio:
   conf = float(state.get("confidence_score") or 1.0)
   risk_tier = state.get("risk_tier", "low")
   routed = list(state.get("routed_agents") or [])

   if conf < settings.confidence_escalation_threshold and risk_tier in ("high", "medium"):
       if "escalation_agent" not in routed:
           return "escalation_agent"
   ```

3. **No arquivo `src/agents/knowledge_agent.py`:**
   Dúvidas puramente informacionais com busca web retornam confiança neutra (0.75 a 0.85) com ressalva textual, sem flag de `insufficient_evidence` que force abertura de chamado.

---

### 5. 🚀 Resolução Implementada

A melhoria foi formalmente implementada através da mudança OpenSpec `escalation-gating-by-risk-tier`:
1. `RouterPlan` em `src/orchestration/state.py` recebeu o atributo `risk_tier: Literal["high", "medium", "low"] = "low"`.
2. O prompt e o motor de classificação determinística em `src/agents/router_agent.py` foram atualizados para categorizar as intenções de acordo com a taxonomia de risco, com overrides determinísticos para tokens financeiros críticos (`chargeback`, `estorno`, `fraude`, `bloqueio`, `balanço`, `faturamento`).
3. O LangGraph em `src/orchestration/graph.py` passou a condicionar o escalonamento automático de baixa confiança exclusivamente aos tiers `high` e `medium`. Consultas de risco `low` encerram o fluxo via `personality_agent` com aviso de evidência insuficiente, sem abrir chamado humano (`handoff_required=False`).
4. Testes dedicados em `tests/unit/test_router.py` e `tests/unit/test_orchestrator.py` foram adicionados e integrados à suíte de testes contínua (100 testes automatizados).
