"""Agent 2 — Knowledge Agent: executes Getnet RAG retrieval and External Web Search."""

from __future__ import annotations

import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from src.config.settings import settings
from src.observability.logger import get_logger
from src.observability.tracer import extract_token_usage, traceable_step
from src.orchestration.state import AgentStepOutput
from src.rag.vector_store import GetnetVectorStore
from src.tools.knowledge_tools import (
    retrieve_getnet_knowledge,
    web_search_general,
)

logger = get_logger("agents.knowledge_agent")

KNOWLEDGE_SYSTEM_PROMPT = """You are Agent 2 (Knowledge Agent) of the Getnet Multi-Agent Support System.
Answer the user's question strictly grounded in the retrieved Getnet Knowledge Base chunks and/or live Web Search results provided below.

Strict Grounding & Direct Entailment Rules (Anti-Hallucination):
1. Always respond in the exact same language as the user's question (Portuguese or English).
2. Direct Entailment Contract: Every specific fact you state—including exact dates, years, founding dates, founders, executive names, interest rates, financial values, and technical specifications—MUST be explicitly and unambiguously written in the provided Tool Context.
3. Anti-Confabulation: You are STRICTLY FORBIDDEN from extrapolating, guessing, or merging disconnected fragments into speculative claims. If snippets mention Santander acquisition in 2014, global PagoNxt/Getnet Europe re-organization in 2015, or general corporate milestones, NEVER state or assume that the company was founded in 2015 or invent co-founders unless an exact sentence in the context explicitly states that fact.
4. Epistemic Transparency / Insufficient Evidence: If the Tool Context (RAG or Web Search) does NOT explicitly and conclusively contain the specific fact requested by the user (for example, the exact founding year of Getnet in Brazil, or unrecorded historical events):
   - You MUST clearly state that the official retrieved records do not contain that specific information.
   - Summarize only the verified milestones that are explicitly present in the context.
   - Append the tag `[INSUFFICIENT_EVIDENCE]` at the very end of your response so the system can calibrate confidence and offer human specialist escalation.
5. If only RAG chunks are provided and they do NOT contain the facts needed to answer the user's specific question, output exactly `[NEEDS_WEB_SEARCH]`.
6. When comparing Get Clássica and Get Smart, clearly contrast the physical keypad vs. Android touchscreen + GetStore apps, noting both have built-in thermal paper roll printers (bobina), Wi-Fi + 3G/4G SIM, and NFC contactless.
7. For Pix, clearly state that a registered bank account (domicílio bancário) in the same CPF/CNPJ (from any bank, or GetConta) is required to receive Pix sales.
8. For Receivables Advance (Antecipação de Recebíveis), explain both Automatic (Plano Receba Já D+1/D+2) and Punctual/On-Demand advance via App Getnet, Portal Minha Getnet, or WhatsApp.
9. For Crediário, state that sales can be split into up to 48 installments (48x) with upfront merchant payout in 2 business days (D+2).
10. For Payment Link (GetPay), confirm merchants can sell directly on WhatsApp without a website or card machine, with credit up to 12 installments (12x), debit, Pix, boleto, and Anti-Fraud protection.
11. For weather or currency exchange rates, report the exact numbers and dates provided in the tool output.
12. If the user asks about or compares a product that does not exist in the official Getnet portfolio (such as 'Get Bronze Water' or any invented terminal), explicitly state that Getnet does not offer such a product, explain the official lineup (Get Tap, Get Mini, Get Lite, Get Clássica, Get Smart), and never invent specifications."""

OFFICIAL_GETNET_POS_MODELS: dict[str, str] = {
    "get classica": "Get Clássica",
    "get clássica": "Get Clássica",
    "classica": "Get Clássica",
    "clássica": "Get Clássica",
    "get smart": "Get Smart",
    "smart": "Get Smart",
    "get lite": "Get Lite",
    "lite": "Get Lite",
    "get mini": "Get Mini",
    "mini": "Get Mini",
    "get tap": "Get Tap",
    "tap": "Get Tap",
}

OFFICIAL_OTHER_PRODUCTS: dict[str, str] = {
    "pix": "Pix",
    "antecipacao": "Antecipação de Recebíveis",
    "antecipação": "Antecipação de Recebíveis",
    "recebiveis": "Recebíveis",
    "recebíveis": "Recebíveis",
    "crediario": "Crediário",
    "crediário": "Crediário",
    "payment link": "Payment Link (GetPay)",
    "link de pagamento": "Link de Pagamento (GetPay)",
    "getpay": "GetPay",
    "getconta": "GetConta",
    "getstore": "GetStore",
}


def detect_queried_and_unknown_entities(message: str) -> tuple[list[str], list[str]]:
    """Detect known and unknown POS terminal or product entities mentioned in the query."""
    known_found: list[str] = []
    unknown_found: list[str] = []

    # Check for direct mentions of known models
    for key, canonical in OFFICIAL_GETNET_POS_MODELS.items():
        if re.search(rf"\b{re.escape(key)}\b", message, flags=re.IGNORECASE):
            if canonical not in known_found:
                known_found.append(canonical)

    # Match any "get <name>" pattern (e.g. "Get Clássica", "Get Bronze Water", "Get Smart")
    get_matches = re.findall(
        r"\bget\s+([a-zA-Zà-ú0-9]+(?:\s+[a-zA-Zà-ú0-9]+)?)\b",
        message,
        flags=re.IGNORECASE,
    )
    for match in get_matches:
        full_candidate = f"get {match.lower().strip()}"
        first_word_candidate = f"get {match.lower().split()[0]}"
        if full_candidate in OFFICIAL_GETNET_POS_MODELS:
            canonical = OFFICIAL_GETNET_POS_MODELS[full_candidate]
            if canonical not in known_found:
                known_found.append(canonical)
        elif first_word_candidate in OFFICIAL_GETNET_POS_MODELS:
            canonical = OFFICIAL_GETNET_POS_MODELS[first_word_candidate]
            if canonical not in known_found:
                known_found.append(canonical)
        elif full_candidate in OFFICIAL_OTHER_PRODUCTS or match.lower().strip() in OFFICIAL_OTHER_PRODUCTS:
            pass
        else:
            cand_stripped = match.lower().strip()
            # Ignore common non-product English/Portuguese words following "get"
            if cand_stripped not in (
                "started", "help", "info", "support", "more", "my", "sales", "a", "an",
                "net", "it", "this", "that", "iniciada", "ajuda", "informacao", "informação"
            ):
                raw_name = f"Get {match.strip()}"
                if raw_name not in unknown_found:
                    unknown_found.append(raw_name)

    return known_found, unknown_found

_OUT_OF_CORPUS_FACT_TERMS: tuple[str, ...] = (
    "inaugurad",
    "fundad",
    "fundaç",
    "fundac",
    "criad",
    "surgiu",
    "história",
    "historia",
    "founded",
    "inaugurated",
    "established",
    "ceo",
    "presidente",
    "diretor",
    "sede",
    "headquarters",
    "ações",
    "acoes",
    "bolsa",
    "ticker",
    "faturamento",
    "lucro",
)

_EPISTEMIC_UNCERTAINTY_MARKERS: tuple[str, ...] = (
    "[insufficient_evidence]",
    "não temos uma data",
    "não há uma data",
    "não há data",
    "sem data exata",
    "não temos a data exata",
    "não temos uma data exata",
    "não há data exata",
    "data exata não consta",
    "data exata é desconhecida",
    "embora não tenhamos",
    "não foi possível confirmar",
    "não encontramos registros",
    "não constam registros",
    "não há registros",
    "não há informações suficientes",
    "informações insuficientes",
    "não constam na documentação",
    "não dispomos",
    "não foi possível localizar",
    "insufficient evidence",
    "exact date is unknown",
    "could not confirm",
    "not explicitly stated",
    "not documented",
    "unverified",
)


def _detect_epistemic_uncertainty(text: str) -> bool:
    """Detect whether the generated answer acknowledges missing, uncertain, or unverified facts."""
    if not text:
        return True
    text_lower = text.lower()
    return any(marker in text_lower for marker in _EPISTEMIC_UNCERTAINTY_MARKERS)


def _rag_chunks_cover_query(
    message: str,
    chunks: list[dict[str, Any]],
    top_similarity: float,
) -> bool:
    """Evaluate whether retrieved RAG chunks genuinely cover the user's question (Corrective RAG gate)."""
    if not chunks or top_similarity < settings.rag_min_similarity_threshold:
        return False

    # Anti-inflation check: if the query mentions an unknown / non-existent entity, RAG does not cover it
    _, unknown_entities = detect_queried_and_unknown_entities(message)
    if unknown_entities:
        return False

    q_lower = message.lower()
    combined_corpus_lower = " ".join(str(c.get("content") or "") for c in chunks[:2]).lower()

    # Check if the user is asking for specific historical/corporate facts absent from the chunks
    for term in _OUT_OF_CORPUS_FACT_TERMS:
        if term in q_lower and term not in combined_corpus_lower:
            return False

    top = chunks[0]
    top_content = str(top.get("content") or "")
    top_tag = str(top.get("product_tag") or "general")
    lexical_boost = GetnetVectorStore._lexical_overlap_boost(message, top_content, top_tag)
    if lexical_boost == 0.0:
        return False

    return True


def _synthesize_unrecognized_entity_response(
    message: str,
    known_entities: list[str],
    unknown_entities: list[str],
    rag_data: dict[str, Any] | None,
) -> str:
    """Build authoritative response when query contains non-existent product entities."""
    is_pt = any(
        w in message.lower()
        for w in ("qual", "diferença", "diferenca", "entre", "maquininha", "como", "o que")
    )
    unknown_str = ", ".join(f"**{u}**" for u in unknown_entities)

    if is_pt:
        parts: list[str] = []
        if known_entities:
            known_str = ", ".join(f"**{k}**" for k in known_entities)
            parts.append(
                f"Em relação ao terminal {known_str}: trata-se de uma maquininha oficial da Getnet para vendas presenciais com chip, tarja, aproximação (NFC) e Pix QR Code."
            )
        parts.append(
            f"No entanto, {unknown_str} **não existe no portfólio oficial de produtos da Getnet**."
        )
        parts.append(
            "O portfólio oficial completo de maquininhas Getnet é composto por 5 modelos:\n"
            "- **Get Tap**: aplicativo gratuito para vender por aproximação direto no celular Android;\n"
            "- **Get Mini**: compacta de bolso com teclado físico e comprovante por SMS;\n"
            "- **Get Lite**: portátil com bateria de longa duração e comprovante por SMS;\n"
            "- **Get Clássica**: modelo robusto de balcão com teclado físico e impressora de bobina térmica embutida;\n"
            "- **Get Smart**: Smart POS Android com tela touchscreen HD, impressora de bobina e loja de aplicativos GetStore."
        )
        return "\n\n".join(parts)

    parts = []
    if known_entities:
        known_str = ", ".join(f"**{k}**" for k in known_entities)
        parts.append(
            f"Regarding {known_str}: this is an official Getnet point-of-sale terminal accepting Chip & PIN, Contactless NFC, and Pix QR Code."
        )
    parts.append(
        f"However, {unknown_str} **does not exist in Getnet's official product portfolio**."
    )
    parts.append(
        "The complete official Getnet card machine lineup consists of 5 models:\n"
        "- **Get Tap**: transform your Android smartphone into a contactless payment terminal;\n"
        "- **Get Mini**: ultra-compact pocket terminal with physical keypad and SMS digital receipt;\n"
        "- **Get Lite**: wireless portable terminal with physical keypad and extended battery life;\n"
        "- **Get Clássica**: robust countertop terminal with physical keypad and built-in thermal paper roll printer (bobina);\n"
        "- **Get Smart**: advanced Android touchscreen Smart POS with built-in thermal paper printer and GetStore business apps."
    )
    return "\n\n".join(parts)


def _synthesize_grounded_knowledge_fallback(
    message: str,
    rag_data: dict[str, Any] | None,
    web_data: dict[str, Any] | None,
) -> str:
    """Zero-mockup grounded synthesis directly from verified RAG chunks and/or live Web Search results."""
    parts: list[str] = []

    if rag_data is not None and rag_data.get("rag_sufficient", False):
        chunks = rag_data.get("chunks") or []
        valid_chunks = [
            str(c.get("content") or "").strip()
            for c in chunks
            if float(c.get("similarity_score") or 0.0) >= settings.rag_min_similarity_threshold
            and str(c.get("content") or "").strip()
        ]
        seen_headers: set[str] = set()
        cleaned_chunks: list[str] = []
        for chunk_text in valid_chunks[:3]:
            lines: list[str] = []
            for line in chunk_text.splitlines():
                stripped = line.strip()
                if stripped.startswith("## ") or stripped.startswith("Source: "):
                    if stripped in seen_headers:
                        continue
                    seen_headers.add(stripped)
                lines.append(line)
            cleaned = "\n".join(lines).strip()
            if cleaned and cleaned not in cleaned_chunks:
                cleaned_chunks.append(cleaned)
        if cleaned_chunks:
            parts.append("\n\n".join(cleaned_chunks))

    if web_data is not None:
        summary = str(web_data.get("summary") or "").strip()
        if summary:
            parts.append(summary)

    if not parts and rag_data is not None:
        for fb in rag_data.get("live_fallback_results") or []:
            if not fb.get("unverified") and fb.get("snippet"):
                parts.append(f"{fb.get('title')}: {fb.get('snippet')} ({fb.get('url')})")

    return "\n\n".join(p for p in parts if p).strip()


@traceable_step(name="knowledge_agent_run", run_type="chain")
def run_knowledge_agent(
    message: str,
    sub_intent: str = "product_rag",
    chat_history: list[dict[str, str]] | None = None,
) -> AgentStepOutput:
    """Execute Agent 2 (Knowledge Agent) with Corrective RAG-to-Web-Search fallback and authentic confidence."""
    tools_used: list[str] = []
    sources: list[str] = []
    raw_data: dict[str, Any] = {}
    rag_data: dict[str, Any] | None = None
    web_data: dict[str, Any] | None = None
    confidence = 0.0
    token_usage: dict[str, int] = {}

    # Strict Entity Coverage Check: if query references non-existent product entities (e.g. "Get Bronze Water")
    known_entities, unknown_entities = detect_queried_and_unknown_entities(message)
    if unknown_entities:
        logger.info(
            "unrecognized_product_entity_detected",
            query=message,
            unknown_entities=unknown_entities,
            known_entities=known_entities,
        )
        rag_data = retrieve_getnet_knowledge(query=message)
        tools_used.append("retrieve_getnet_knowledge")
        rag_data["rag_sufficient"] = False
        rag_data["unknown_entities"] = unknown_entities
        rag_data["known_entities"] = known_entities
        raw_data["rag"] = rag_data

        fallback_answer = _synthesize_unrecognized_entity_response(
            message=message,
            known_entities=known_entities,
            unknown_entities=unknown_entities,
            rag_data=rag_data,
        )
        sources = ["https://site.getnet.com.br/maquininhas/"]
        confidence = 0.92

        if settings.use_live_llm:
            try:  # pragma: no cover
                llm = ChatOpenAI(
                    model=settings.openai_model,
                    temperature=settings.openai_temperature_agent,
                    api_key=settings.openai_api_key,
                    timeout=8.0,
                    max_retries=1,
                )
                resp = llm.invoke(
                    [
                        SystemMessage(content=KNOWLEDGE_SYSTEM_PROMPT),
                        HumanMessage(
                            content=(
                                f"Grounded Context:\n{fallback_answer}\nSources: {sources}\n\n"
                                f"User Question: {message}\n\n"
                                f"Instructions: Clarify that {', '.join(unknown_entities)} does not exist in Getnet's official lineup, and explain any known models queried."
                            )
                        ),
                    ]
                )
                token_usage = extract_token_usage(resp)
                llm_text = str(resp.content).strip()
                if llm_text:
                    return AgentStepOutput(
                        agent_name="knowledge_agent",
                        content=llm_text,
                        tools_used=tools_used,
                        sources=sources,
                        confidence=confidence,
                        raw_data=raw_data,
                        token_usage=token_usage,
                    )
            except Exception as exc:  # pragma: no cover
                logger.warning("knowledge_agent_unknown_entity_llm_fallback", error=str(exc))

        return AgentStepOutput(
            agent_name="knowledge_agent",
            content=fallback_answer,
            tools_used=tools_used,
            sources=sources,
            confidence=confidence,
            raw_data=raw_data,
            token_usage=token_usage,
        )

    if sub_intent in ("product_rag", "both", "none"):
        rag_data = retrieve_getnet_knowledge(query=message)
        tools_used.append("retrieve_getnet_knowledge")
        top_sim = float(rag_data.get("top_similarity", 0.0))
        chunks = list(rag_data.get("chunks") or [])

        rag_sufficient = _rag_chunks_cover_query(
            message=message,
            chunks=chunks,
            top_similarity=top_sim,
        )
        rag_data["rag_sufficient"] = rag_sufficient

        if rag_sufficient:
            sources.extend(rag_data.get("sources") or [])
            confidence = round(min(0.98, top_sim), 4)
        else:
            # Corrective RAG: discard irrelevant RAG chunks and escalate dynamically to live Web Search
            logger.info(
                "corrective_rag_to_web_search_triggered",
                query=message,
                top_similarity=top_sim,
            )
            rag_data["discarded_chunks_count"] = len(chunks)
            rag_data["chunks"] = []
            confidence = round(top_sim, 4)
            if sub_intent != "both":
                sub_intent = "both"

        raw_data["rag"] = rag_data

    if sub_intent in ("external_web_search", "both"):
        web_data = web_search_general(query=message)
        if "web_search_general" not in tools_used:
            tools_used.append("web_search_general")
        raw_data["web_search"] = web_data
        verified = bool(web_data.get("verified_results", True)) and bool(
            str(web_data.get("summary") or "").strip()
        )
        if verified:
            sources.extend(web_data.get("sources") or [])
            if sub_intent == "external_web_search":
                confidence = max(confidence, 0.88)
            else:
                # Corrective RAG: we escalated out of corpus; start with cautious baseline (escalates if inconclusive)
                confidence = 0.55
        else:
            # Neither RAG nor Web Search produced verified content -> keep low confidence (< 0.60) for escalation
            confidence = round(min(confidence if confidence > 0 else 0.30, 0.45), 4)

    dedup_sources = list(dict.fromkeys(s for s in sources if s))
    fallback_answer = _synthesize_grounded_knowledge_fallback(
        message=message,
        rag_data=rag_data,
        web_data=web_data,
    )

    if settings.use_live_llm:
        try:  # pragma: no cover
            llm = ChatOpenAI(
                model=settings.openai_model,
                temperature=settings.openai_temperature_agent,
                api_key=settings.openai_api_key,
                timeout=8.0,
                max_retries=1,
            )
            context_block = f"Grounded Tool Context:\n{fallback_answer}\nSources: {dedup_sources}"
            history_ctx = ""
            if chat_history:
                history_lines = [
                    f"{m.get('role', 'user').capitalize()}: {m.get('content', '')}"
                    for m in chat_history[-4:]
                ]
                history_ctx = "Prior Conversation Turns:\n" + "\n".join(history_lines) + "\n\n"

            resp = llm.invoke(
                [
                    SystemMessage(content=KNOWLEDGE_SYSTEM_PROMPT),
                    HumanMessage(content=f"{history_ctx}{context_block}\n\nUser Question: {message}"),
                ]
            )
            token_usage = extract_token_usage(resp)
            llm_text = str(resp.content).strip()

            # Stage 2 LLM Corrective RAG check: if LLM detects RAG chunks did not answer the question
            if "[NEEDS_WEB_SEARCH]" in llm_text and web_data is None:
                logger.info("llm_corrective_web_search_triggered", query=message)
                if rag_data is not None:
                    rag_data["rag_sufficient"] = False
                    rag_data["chunks"] = []
                web_data = web_search_general(query=message)
                if "web_search_general" not in tools_used:
                    tools_used.append("web_search_general")
                raw_data["web_search"] = web_data
                if web_data.get("verified_results", True) and str(web_data.get("summary") or "").strip():
                    dedup_sources = list(dict.fromkeys(s for s in (web_data.get("sources") or []) if s))
                    confidence = 0.55
                    fallback_answer = _synthesize_grounded_knowledge_fallback(
                        message=message,
                        rag_data=rag_data,
                        web_data=web_data,
                    )
                    retry_resp = llm.invoke(
                        [
                            SystemMessage(content=KNOWLEDGE_SYSTEM_PROMPT),
                            HumanMessage(
                                content=f"Grounded Web Search Context:\n{fallback_answer}\nSources: {dedup_sources}\n\nUser Question: {message}"
                            ),
                        ]
                    )
                    retry_usage = extract_token_usage(retry_resp)
                    if retry_usage:
                        token_usage = {
                            "prompt_tokens": token_usage.get("prompt_tokens", 0) + retry_usage.get("prompt_tokens", 0),
                            "completion_tokens": token_usage.get("completion_tokens", 0) + retry_usage.get("completion_tokens", 0),
                            "total_tokens": token_usage.get("total_tokens", 0) + retry_usage.get("total_tokens", 0),
                        }
                    llm_text = str(retry_resp.content).strip()
                else:
                    confidence = 0.40
                    llm_text = ""

            insufficient_evidence = (
                "[INSUFFICIENT_EVIDENCE]" in llm_text
                or raw_data.get("insufficient_evidence", False)
                or _detect_epistemic_uncertainty(llm_text)
            )
            if insufficient_evidence:
                raw_data["insufficient_evidence"] = True
                confidence = round(min(confidence, 0.45), 4)
                llm_text = llm_text.replace("[INSUFFICIENT_EVIDENCE]", "").strip()
            elif (sub_intent in ("both", "external_web_search")) and verified:
                confidence = 0.88

            if llm_text and "[NEEDS_WEB_SEARCH]" not in llm_text:
                return AgentStepOutput(
                    agent_name="knowledge_agent",
                    content=llm_text,
                    tools_used=tools_used,
                    sources=dedup_sources,
                    confidence=confidence,
                    raw_data=raw_data,
                    token_usage=token_usage,
                )
        except Exception as exc:  # pragma: no cover
            logger.warning("knowledge_agent_llm_fallback", error=str(exc))

    if not fallback_answer:
        fallback_answer = (
            "Não encontramos informações verificadas suficientes na base de conhecimento ou na busca web "
            "para responder com segurança a esta pergunta. Encaminhando para um especialista humano Getnet."
        )
        confidence = 0.40
    elif raw_data.get("insufficient_evidence", False):
        confidence = round(min(confidence, 0.45), 4)

    return AgentStepOutput(
        agent_name="knowledge_agent",
        content=fallback_answer,
        tools_used=tools_used,
        sources=dedup_sources,
        confidence=confidence,
        raw_data=raw_data,
        token_usage=token_usage,
    )
