"""Agent 5 — Personality & Response Synthesis Agent: unifies outputs in Getnet's brand voice."""

from __future__ import annotations

from typing import Any, Iterator

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from src.config.settings import settings
from src.observability.logger import get_logger
from src.observability.tracer import extract_token_usage, traceable_step

logger = get_logger("agents.personality_agent")

PERSONALITY_SYSTEM_PROMPT = """You are Agent 5 (Personality & Output Synthesis Agent) of the Getnet Multi-Agent Support System.
Your role is to synthesize the intermediate outputs produced by Getnet's specialized agents (Knowledge Agent, Customer Support Agent, and/or Human Escalation Agent) into a single, clear, empathetic, and merchant-friendly response.
Rules:
1. Preserve 100% of the factual details, numbers, dates, error codes (e.g., ISO-8583 Code 51), installment limits (up to 48x), and troubleshooting steps retrieved by the specialized agents.
2. Respond in the same language as the user's message (English or Portuguese).
3. Keep the tone professional, warm, and action-oriented, representing Getnet's official support voice.
4. When a Human Specialist Handoff is initiated (handoff_required=True or findings from Human Escalation Agent):
   - If the inquiry was about a topic or historical period not conclusively documented in Getnet's public technical knowledge base, explicitly and transparently explain that the official records do not contain verified confirmation of those specific details.
   - Reassure the merchant that, to ensure total accuracy without speculation, their request has been transferred to a human specialist.
   - Always prominently highlight the Protocol ID (`protocol_id`) and linked support ticket from the Escalation Agent findings.
5. If the specialized findings state that a product model or entity does not exist in Getnet's official portfolio (e.g., "does not exist in Getnet's official product portfolio" / "não existe no portfólio oficial"), you MUST explicitly state that this entity does not exist in Getnet's catalog. Never omit this critical factual correction."""


@traceable_step(name="personality_agent_synthesize", run_type="chain")
def run_personality_agent(
    message: str,
    user_id: str,
    agent_outputs: list[dict[str, Any]],
    language: str = "en",
    handoff_required: bool = False,
    chat_history: list[dict[str, str]] | None = None,
) -> tuple[str, dict[str, int]]:
    """Combine one or more specialized agent outputs into a cohesive Getnet support response."""
    token_usage: dict[str, int] = {}

    if not agent_outputs:
        if language == "pt":
            return (
                f"Olá, **{user_id}**! Sou o assistente virtual da Getnet. Não consegui identificar uma dúvida ou "
                "solicitação válida na sua mensagem. Estou à disposição para ajudar com informações sobre nossas maquininhas "
                "(Get Smart, Get Clássica, Get Lite, Get Mini, Get Tap), Pix, Antecipação de Recebíveis, Link de Pagamento (GetPay) "
                "ou suporte técnico ao seu terminal e conta. Como posso te ajudar hoje?",
                token_usage,
            )
        return (
            f"Hello, **{user_id}**! I am Getnet's virtual support assistant. I could not identify a valid question or "
            "request in your message. I am here to help you with Getnet card machines (Get Smart, Get Clássica, Get Lite, Get Mini, Get Tap), "
            "Pix, Receivables Advance, Payment Link (GetPay), or technical support for your terminal and merchant account. How can I assist you today?",
            token_usage,
        )

    blocks = [str(item.get("content") or "").strip() for item in agent_outputs if item.get("content")]
    merged_core = "\n\n---\n\n".join(blocks)

    if language == "pt":
        greeting = f"Olá, **{user_id}**! Aqui estão as informações do atendimento Getnet:\n\n"
        closing = (
            "\n\nUm especialista humano da Getnet assumirá este atendimento em instantes."
            if handoff_required
            else "\n\nSe precisar de mais alguma ajuda com suas vendas ou maquininha Getnet, estou à disposição!"
        )
    else:
        greeting = f"Hello, **{user_id}**! Here is the information from Getnet Support:\n\n"
        closing = (
            "\n\nA Getnet human specialist has been notified and will join this conversation shortly."
            if handoff_required
            else "\n\nPlease let me know if you need any further assistance with your Getnet products or account!"
        )

    deterministic_response = f"{greeting}{merged_core}{closing}"

    if settings.use_live_llm:
        try:  # pragma: no cover
            llm = ChatOpenAI(
                model=settings.openai_model,
                temperature=settings.openai_temperature_personality,
                api_key=settings.openai_api_key,
                timeout=12.0,
            )
            history_ctx = ""
            if chat_history:
                history_lines = [
                    f"{m.get('role', 'user').capitalize()}: {m.get('content', '')}"
                    for m in chat_history[-4:]
                ]
                history_ctx = "Prior Conversation Dialogue:\n" + "\n".join(history_lines) + "\n\n"

            resp = llm.invoke(
                [
                    SystemMessage(content=PERSONALITY_SYSTEM_PROMPT),
                    HumanMessage(
                        content=(
                            f"Merchant user_id: {user_id}\n"
                            f"Detected Language: {language}\n"
                            f"Handoff Required: {handoff_required}\n"
                            f"{history_ctx}"
                            f"Original Message: {message}\n\n"
                            f"Specialized Agent Findings:\n{merged_core}"
                        )
                    ),
                ]
            )
            token_usage = extract_token_usage(resp)
            synthesized = str(resp.content).strip()
            if synthesized:
                return synthesized, token_usage
        except Exception as exc:  # pragma: no cover
            logger.warning("personality_agent_llm_fallback", error=str(exc))

    return deterministic_response, token_usage


def stream_personality_agent(
    message: str,
    user_id: str,
    agent_outputs: list[dict[str, Any]],
    language: str = "en",
    handoff_required: bool = False,
    chat_history: list[dict[str, str]] | None = None,
) -> Iterator[str]:
    """Yield incremental response text chunks as they are generated by the Personality Agent."""
    if not agent_outputs:
        deterministic_resp, _ = run_personality_agent(
            message=message,
            user_id=user_id,
            agent_outputs=agent_outputs,
            language=language,
            handoff_required=handoff_required,
            chat_history=chat_history,
        )
        yield deterministic_resp
        return

    blocks = [str(item.get("content") or "").strip() for item in agent_outputs if item.get("content")]
    merged_core = "\n\n---\n\n".join(blocks)

    if language == "pt":
        greeting = f"Olá, **{user_id}**! Aqui estão as informações do atendimento Getnet:\n\n"
        closing = (
            "\n\nUm especialista humano da Getnet assumirá este atendimento em instantes."
            if handoff_required
            else "\n\nSe precisar de mais alguma ajuda com suas vendas ou maquininha Getnet, estou à disposição!"
        )
    else:
        greeting = f"Hello, **{user_id}**! Here is the information from Getnet Support:\n\n"
        closing = (
            "\n\nA Getnet human specialist has been notified and will join this conversation shortly."
            if handoff_required
            else "\n\nPlease let me know if you need any further assistance with your Getnet products or account!"
        )

    deterministic_response = f"{greeting}{merged_core}{closing}"

    if settings.use_live_llm:
        try:  # pragma: no cover
            llm = ChatOpenAI(
                model=settings.openai_model,
                temperature=settings.openai_temperature_personality,
                api_key=settings.openai_api_key,
                timeout=12.0,
            )
            history_ctx = ""
            if chat_history:
                history_lines = [
                    f"{m.get('role', 'user').capitalize()}: {m.get('content', '')}"
                    for m in chat_history[-4:]
                ]
                history_ctx = "Prior Conversation Dialogue:\n" + "\n".join(history_lines) + "\n\n"

            messages = [
                SystemMessage(content=PERSONALITY_SYSTEM_PROMPT),
                HumanMessage(
                    content=(
                        f"Merchant user_id: {user_id}\n"
                        f"Detected Language: {language}\n"
                        f"Handoff Required: {handoff_required}\n"
                        f"{history_ctx}"
                        f"Original Message: {message}\n\n"
                        f"Specialized Agent Findings:\n{merged_core}"
                    )
                ),
            ]
            for chunk in llm.stream(messages):
                token_text = str(chunk.content or "")
                if token_text:
                    yield token_text
            return
        except Exception as exc:  # pragma: no cover
            logger.warning("personality_agent_llm_stream_fallback", error=str(exc))

    # Deterministic fallback streaming (word-by-word emission)
    words = deterministic_response.split(" ")
    for idx, word in enumerate(words):
        yield word + (" " if idx < len(words) - 1 else "")
