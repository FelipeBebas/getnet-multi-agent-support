"""Agent 1 — Router Agent: classifies intent and builds single-agent or sequential multi-agent plans."""

from __future__ import annotations

import re

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from src.config.settings import settings
from src.observability.logger import get_logger
from src.observability.tracer import traceable_step
from src.orchestration.state import RouterPlan, SpecializedAgentName

logger = get_logger("agents.router_agent")

ROUTER_SYSTEM_PROMPT = """You are Agent 1 (Router Agent) of the Getnet Multi-Agent Support System.
Your job is to analyze the incoming merchant message and determine which specialized agent (or ordered sequence of agents) must handle it:

1. `knowledge_agent`:
   - Handles all Getnet institutional, product, hardware, and pricing questions via RAG (`knowledge_sub_intent="product_rag"`): POS terminals (Get Clássica, Get Smart, Get Lite, Get Mini, Get Tap), Pix bank account (domicílio bancário) requirements, Receivables Advance (antecipação de recebíveis), Crediário installment limits (up to 48x), and selling via WhatsApp Payment Link (GetPay).
   - Handles general-purpose real-time external questions via Web Search (`knowledge_sub_intent="external_web_search"`): weather forecasts (e.g. Porto Alegre tomorrow), currency exchange rates (e.g. Euro exchange rate today), or general news.

2. `customer_support_agent`:
   - Handles merchant-specific account and technical troubleshooting scoped to `user_id`:
     * `support_sub_intent="settlement"`: deposit schedule for yesterday's sales, pending receivables, bank payout status.
     * `support_sub_intent="pos_connectivity"`: card machine won't connect to the internet, Wi-Fi, or 4G SIM errors.
     * `support_sub_intent="transaction_decline"`: card machine showing a transaction decline error or ISO-8583 code.
     * `support_sub_intent="ticket"`: opening or checking a technical support / terminal replacement ticket.

3. `escalation_agent`:
   - Handles explicit requests to speak with a human operator/attendant/supervisor, severe legal/chargeback disputes, or out-of-scope high-risk account complaints.

4. `out_of_scope`:
   - Messages that are test noise (e.g. "123 teste block"), random gibberish, empty greetings, or completely unrelated chit-chat with no acquiring/support intent. Set `primary_intent="out_of_scope"` and leave `agent_queue` empty (`[]`).

If a message combines multiple intents (for example, asking a product/knowledge question AND checking yesterday's sales deposit or POS status), include both agents in `agent_queue` in logical order: `["knowledge_agent", "customer_support_agent"]`.
Detect whether the message is in English (`"en"`) or Portuguese (`"pt"`)."""


def detect_language(message: str) -> str:
    """Detect whether the message is primarily Portuguese ('pt') or English ('en')."""
    msg = message.lower()
    pt_markers = (
        "qual ",
        "quais ",
        "como ",
        "quando ",
        "quem ",
        "onde ",
        "minha ",
        "maquininha",
        "vendas de ontem",
        "preciso",
        "posso",
        "diferença",
        "cotação",
        "previsão",
        "atendente",
        "cartão",
        "não conecta",
        "inaugurada",
        "fundada",
        "história",
        "foi ",
        "está ",
        "teste",
        "olá",
        "ola",
        "bom dia",
        "boa tarde",
        "boa noite",
    )
    if any(m in msg for m in pt_markers):
        return "pt"
    return "en"


def is_elliptical_query(message: str) -> bool:
    """Determine if a query is likely an elliptical follow-up that depends on prior turns."""
    q = message.lower().strip()
    words = q.split()
    if len(words) <= 6:
        elliptical_starters = (
            "what about",
            "how about",
            "what of",
            "and for",
            "and in",
            "and with",
            "and what",
            "e sobre",
            "e o",
            "e a",
            "e no",
            "e na",
            "e para",
            "e com",
            "e se",
            "quanto a",
            "quanto à",
            "quanto ao",
            "e quanto",
        )
        if any(q.startswith(s) for s in elliptical_starters):
            return True

    pronoun_patterns = (
        r"\b(?:quanto\s+custa\s+ela|quanto\s+é\s+ela|qual\s+o\s+valor\s+dela)\b",
        r"\b(?:how\s+much\s+is\s+it|how\s+much\s+does\s+it\s+cost)\b",
        r"\b(?:e\s+no\s+d[eé]bito|e\s+no\s+cr[eé]dito)\b",
        r"\b(?:e\s+as\s+taxas\s+dela|e\s+o\s+aluguel\s+dela)\b",
    )
    if any(re.search(p, q) for p in pronoun_patterns):
        return True

    return False


def rewrite_contextual_query(
    message: str,
    chat_history: list[dict[str, str]] | None = None,
) -> str:
    """Rewrite elliptical follow-ups into standalone queries using prior dialogue context."""
    if not chat_history or not is_elliptical_query(message):
        return message

    user_turns = [
        str(m.get("content") or "").strip()
        for m in chat_history
        if m.get("role") == "user" and str(m.get("content") or "").strip()
    ]
    if not user_turns:
        return message

    last_user_turn = user_turns[-1]
    last_lower = last_user_turn.lower()
    q_lower = message.lower().strip()

    # 1. Currency Exchange follow-up (e.g. "What's the euro exchange rate today?" -> "what about yen?")
    fx_topics = (
        "exchange rate", "cotação", "cotacao", "câmbio", "cambio",
        "euro", "dollar", "usd", "dólar", "moeda", "yen", "iene", "jpy"
    )
    if any(k in last_lower for k in fx_topics):
        currencies = {
            "yen": "Japanese Yen (JPY)",
            "iene": "Iene Japonês (JPY)",
            "jpy": "Japanese Yen (JPY)",
            "dollar": "US Dollar (USD)",
            "dólar": "Dólar Americano (USD)",
            "dolar": "Dólar Americano (USD)",
            "usd": "US Dollar (USD)",
            "pound": "British Pound (GBP)",
            "libra": "Libra Esterlina (GBP)",
            "gbp": "British Pound (GBP)",
            "euro": "Euro (EUR)",
            "eur": "Euro (EUR)",
        }
        for curr_key, curr_full in currencies.items():
            if curr_key in q_lower:
                lang = "pt" if detect_language(message) == "pt" or detect_language(last_user_turn) == "pt" else "en"
                if lang == "pt":
                    return f"Qual é a cotação do {curr_full} hoje?"
                return f"What is the exchange rate for {curr_full} today?"

    # 2. Weather forecast follow-up
    if any(k in last_lower for k in ("weather", "clima", "tempo", "forecast", "previsão", "previsao")):
        city_match = re.search(r"(?:about|for|em|para|de)\s+([a-zA-ZÀ-ÿ\s]+)[?!.]*$", q_lower)
        if city_match:
            city = city_match.group(1).strip().title()
            lang = "pt" if detect_language(message) == "pt" or detect_language(last_user_turn) == "pt" else "en"
            if lang == "pt":
                return f"Qual a previsão do tempo em {city} amanhã?"
            return f"What's the weather forecast in {city} tomorrow?"

    # 3. Terminal hardware / specs / pricing follow-up
    terminal_topics = ("get clássica", "get classica", "get smart", "get mini", "get lite", "maquininha")
    if any(k in last_lower for k in terminal_topics):
        if any(k in q_lower for k in ("quanto custa", "valor", "preço", "preco", "aluguel", "cost", "price", "rent", "taxa")):
            terminals = []
            if "clássica" in last_lower or "classica" in last_lower:
                terminals.append("Get Clássica")
            if "smart" in last_lower:
                terminals.append("Get Smart")
            term_str = " e ".join(terminals) if terminals else "maquininhas Getnet"
            lang = "pt" if detect_language(message) == "pt" else "en"
            if lang == "pt":
                return f"Qual o valor do aluguel e taxas da {term_str}?"
            return f"What is the rental price and fees for the {term_str}?"

    # 4. Payment rates follow-up
    if "pix" in last_lower or "taxa" in last_lower:
        if "débito" in q_lower or "debito" in q_lower or "debit" in q_lower:
            return "Qual é a taxa de débito na maquininha Getnet?"
        if "crédito" in q_lower or "credito" in q_lower or "credit" in q_lower:
            return "Qual é a taxa de crédito na maquininha Getnet?"

    # 5. Live LLM Rewriter fallback
    if settings.use_live_llm:
        try:  # pragma: no cover
            llm = ChatOpenAI(
                model=settings.openai_model,
                temperature=0.0,
                api_key=settings.openai_api_key,
                timeout=4.0,
                max_retries=1,
            )
            history_text = "\n".join(
                f"{m.get('role', 'user').capitalize()}: {m.get('content', '')}"
                for m in chat_history[-4:]
            )
            prompt = (
                "You are an expert Query Rewriter for Getnet Payment Services.\n"
                "Given the conversation history and the user's latest follow-up question, rewrite it into a single, complete, standalone search query.\n"
                "Keep the same language as the user's message (Portuguese or English).\n"
                "Output ONLY the rewritten query text, with no explanations.\n\n"
                f"Conversation History:\n{history_text}\n\n"
                f"Follow-up Question: {message}\n"
                "Standalone Query:"
            )
            resp = llm.invoke([HumanMessage(content=prompt)])
            rewritten = str(resp.content).strip().strip('"').strip("'")
            if rewritten and len(rewritten) > 3:
                return rewritten
        except Exception as exc:  # pragma: no cover
            logger.warning("llm_query_rewriter_fallback", error=str(exc))

    return message


def _deterministic_route(message: str, user_id: str = "") -> RouterPlan:
    """High-precision deterministic intent classifier covering all single and hybrid scenarios."""
    q = message.lower().strip()
    lang = "pt" if detect_language(message) == "pt" else "en"

    # 1. Check for explicit Human Escalation intent
    escalation_terms = (
        "human operator",
        "human agent",
        "human attendant",
        "speak to a human",
        "talk to a human",
        "speak with a person",
        "atendente humano",
        "falar com humano",
        "falar com um atendente",
        "falar com especialista",
        "supervisor",
        "ombudsman",
        "ouvidoria",
        "chargeback fraud dispute",
        "contestação de fraude",
    )
    wants_escalation = any(t in q for t in escalation_terms)

    # 2. Check for Customer Support sub-intents (account/device specific)
    settlement_patterns = (
        r"yesterday'?s\s+sales",
        r"money\s+from\s+yesterday",
        r"when\s+will\s+the\s+money.*deposited",
        r"when\s+will\s+my\s+sales.*deposited",
        r"my\s+deposit",
        r"my\s+settlement",
        r"vendas\s+de\s+ontem",
        r"dinheiro\s+das\s+vendas",
        r"quando\s+cai\s+o\s+dinheiro",
        r"meu\s+repasse",
    )
    pos_conn_patterns = (
        r"won'?t\s+connect\s+to\s+the\s+internet",
        r"not\s+connecting\s+to\s+(?:the\s+)?internet",
        r"card\s+machine\s+won'?t\s+connect",
        r"terminal\s+offline",
        r"wifi\s+error",
        r"wi-fi\s+error",
        r"não\s+conecta\s+na\s+internet",
        r"nao\s+conecta\s+na\s+internet",
        r"maquininha\s+sem\s+sinal",
        r"maquininha\s+não\s+conecta",
    )
    decline_patterns = (
        r"transaction\s+decline\s+error",
        r"showing\s+a\s+transaction\s+decline",
        r"decline\s+error",
        r"card\s+declined\s+on\s+my\s+machine",
        r"error\s+code\s+\d+",
        r"transação\s+negada",
        r"transacao\s+negada",
        r"erro\s+de\s+transação",
        r"erro\s+na\s+maquininha",
    )
    ticket_patterns = (
        r"open\s+a\s+(?:support\s+)?ticket",
        r"create\s+a\s+(?:support\s+)?ticket",
        r"check\s+my\s+ticket",
        r"replace\s+my\s+card\s+machine",
        r"abrir\s+(?:um\s+)?chamado",
        r"protocolo\s+de\s+suporte",
        r"trocar\s+minha\s+maquininha",
    )

    has_settlement = any(re.search(p, q) for p in settlement_patterns)
    has_pos_conn = any(re.search(p, q) for p in pos_conn_patterns)
    has_decline = any(re.search(p, q) for p in decline_patterns)
    has_ticket = any(re.search(p, q) for p in ticket_patterns)
    wants_support = has_settlement or has_pos_conn or has_decline or has_ticket

    support_types_count = sum(
        [bool(has_settlement), bool(has_pos_conn), bool(has_decline), bool(has_ticket)]
    )
    if support_types_count > 1:
        support_sub: str = "all"
    elif has_settlement:
        support_sub = "settlement"
    elif has_pos_conn:
        support_sub = "pos_connectivity"
    elif has_decline:
        support_sub = "transaction_decline"
    elif has_ticket:
        support_sub = "ticket"
    else:
        support_sub = "none"

    # 3. Check for Knowledge sub-intents (Product RAG vs. External Web Search)
    web_search_patterns = (
        r"weather\s+forecast",
        r"weather\s+in\s+",
        r"previsão\s+do\s+tempo",
        r"previsao\s+do\s+tempo",
        r"clima\s+em\s+",
        r"exchange\s+rate",
        r"euro\s+today",
        r"euro\s+exchange",
        r"cotação\s+do\s+euro",
        r"cotacao\s+do\s+euro",
        r"taxa\s+de\s+câmbio",
        r"dollar\s+exchange",
    )
    product_rag_patterns = (
        r"get\s+cl[aá]ssica",
        r"get\s+smart",
        r"get\s+lite",
        r"get\s+mini",
        r"get\s+tap",
        r"difference\s+between",
        r"diferença\s+entre",
        r"receive\s+my\s+sales\s+via\s+pix",
        r"bank\s+account.*pix",
        r"conta\s+banc[aá]ria.*pix",
        r"domic[ií]lio\s+banc[aá]rio",
        r"receivables\s+advance",
        r"antecip[aã][cç][aã]o",
        r"credi[aá]rio",
        r"how\s+many\s+installments",
        r"quantas\s+parcelas",
        r"payment\s+link",
        r"link\s+de\s+pagamento",
        r"getpay",
        r"sell\s+through\s+whatsapp",
        r"vender\s+pelo\s+whatsapp",
        r"getnet",
    )

    has_web = any(re.search(p, q) for p in web_search_patterns)
    has_rag = any(re.search(p, q) for p in product_rag_patterns)

    # Avoid classifying "with Getnet" in a pure support query as a separate RAG query unless product terms exist
    if wants_support and not any(
        re.search(p, q) for p in product_rag_patterns[:-1]
    ):
        has_rag = False

    wants_knowledge = has_web or has_rag
    if has_web and has_rag:
        knowledge_sub = "both"
    elif has_web:
        knowledge_sub = "external_web_search"
    elif has_rag:
        knowledge_sub = "product_rag"
    else:
        knowledge_sub = "none"

    # Check for Out-of-Scope / Noise input (e.g. "123 teste block", pure numbers, random noise)
    noise_tokens = {
        "teste", "test", "testing", "block", "bloqueio", "123", "abc", "asdf",
        "qwerty", "foo", "bar", "baz", "ola", "olá", "oi", "hello", "hi", "hey"
    }
    words = [w for w in re.findall(r"[a-zA-Z0-9à-ú]+", q) if len(w) > 0]
    is_pure_noise = (
        bool(words)
        and all(w in noise_tokens or w.isdigit() for w in words)
        and not wants_support
        and not wants_escalation
        and "getnet" not in q
    )
    is_symbol_or_digit_only = bool(re.fullmatch(r"[\d\s\W_]+", q))

    if is_pure_noise or is_symbol_or_digit_only:
        return RouterPlan(
            primary_intent="out_of_scope",
            agent_queue=[],
            knowledge_sub_intent="none",
            support_sub_intent="none",
            confidence=0.95,
            language=lang,
            reasoning="Message classified as out-of-scope / test noise with no acquiring or support intent.",
        )

    queue: list[SpecializedAgentName] = []
    if wants_knowledge:
        queue.append("knowledge_agent")
    if wants_support:
        queue.append("customer_support_agent")
    if wants_escalation:
        queue.append("escalation_agent")

    # Default fallback if no explicit keyword matched: route to Knowledge Agent (RAG)
    if not queue:
        queue.append("knowledge_agent")
        knowledge_sub = "product_rag"

    if len(queue) > 1:
        primary_intent = "hybrid"
    elif queue[0] == "knowledge_agent":
        primary_intent = "knowledge"
    elif queue[0] == "customer_support_agent":
        primary_intent = "customer_support"
    else:
        primary_intent = "escalation"

    confidence = 0.96 if (wants_knowledge or wants_support or wants_escalation) else 0.78
    reasoning = (
        f"Classified intent as '{primary_intent}' -> queue={queue} "
        f"(knowledge_sub='{knowledge_sub}', support_sub='{support_sub}', user_id='{user_id}')."
    )

    return RouterPlan(
        primary_intent=primary_intent,  # type: ignore[arg-type]
        agent_queue=queue,
        knowledge_sub_intent=knowledge_sub,  # type: ignore[arg-type]
        support_sub_intent=support_sub,  # type: ignore[arg-type]
        confidence=confidence,
        language=lang,  # type: ignore[arg-type]
        reasoning=reasoning,
    )


@traceable_step(name="router_agent_classify", run_type="chain")
def classify_and_route(
    message: str,
    user_id: str = "",
    chat_history: list[dict[str, str]] | None = None,
) -> RouterPlan:
    """Execute Agent 1 (Router Agent) using contextual query rewriting and structured LLM routing."""
    rewritten = rewrite_contextual_query(message=message, chat_history=chat_history)
    deterministic_plan = _deterministic_route(message=rewritten, user_id=user_id)
    deterministic_plan.rewritten_query = rewritten

    if not settings.use_live_llm:
        return deterministic_plan

    try:  # pragma: no cover
        llm = ChatOpenAI(
            model=settings.openai_model,
            temperature=settings.openai_temperature_router,
            api_key=settings.openai_api_key,
            timeout=6.0,
            max_retries=1,
        )
        structured_llm = llm.with_structured_output(RouterPlan)
        history_context = ""
        if chat_history:
            history_lines = [
                f"{m.get('role', 'user').capitalize()}: {m.get('content', '')}"
                for m in chat_history[-4:]
            ]
            history_context = f"\nRecent History:\n" + "\n".join(history_lines)

        llm_plan = structured_llm.invoke(
            [
                SystemMessage(content=ROUTER_SYSTEM_PROMPT),
                HumanMessage(
                    content=(
                        f"user_id: {user_id}\n"
                        f"message: {rewritten}"
                        f"{history_context}"
                    )
                ),
            ]
        )
        if isinstance(llm_plan, RouterPlan):
            llm_plan.rewritten_query = rewritten
            if llm_plan.primary_intent == "out_of_scope" or llm_plan.agent_queue:
                return llm_plan
    except Exception as exc:  # pragma: no cover
        logger.warning("router_llm_fallback_to_deterministic", error=str(exc))

    return deterministic_plan
