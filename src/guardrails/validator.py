"""Input safety/prompt-injection guardrails and Output PCI-DSS PAN & PII redaction."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from src.config.settings import settings
from src.observability.logger import get_logger
from src.observability.tracer import traceable_step

logger = get_logger("guardrails.validator")

_PROMPT_INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "instruction_override",
        re.compile(
            r"(?:ignore|disregard|forget|override|bypass)\s+(?:all\s+)?(?:previous|prior|above|system|safety)\s+"
            r"(?:instructions|prompts|rules|guardrails)",
            re.IGNORECASE,
        ),
    ),
    (
        "instruction_override_pt",
        re.compile(
            r"(?:ignore|esqueça|esqueca|desconsidere|burlar)\s+(?:todas\s+as\s+|as\s+)?"
            r"(?:instruções|instrucoes|regras|diretrizes)\s+(?:anteriores|do\s+sistema|de\s+segurança)?",
            re.IGNORECASE,
        ),
    ),
    (
        "system_prompt_extraction",
        re.compile(
            r"(?:reveal|show|print|output|repeat|dump)\s+(?:your\s+|the\s+)?"
            r"(?:system\s+prompt|hidden\s+instructions|secret\s+key|openai_api_key|all\s+merchant\s+records|database)",
            re.IGNORECASE,
        ),
    ),
    (
        "jailbreak_persona",
        re.compile(
            r"\b(?:jailbreak|dan\s+mode|developer\s+mode|act\s+as\s+an\s+unrestricted|sem\s+restrições\s+de\s+segurança)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "sql_or_command_injection",
        re.compile(
            r"(?:;\s*drop\s+table|union\s+select\s+|os\.system\(|subprocess\.popen\()",
            re.IGNORECASE,
        ),
    ),
]

_UNSAFE_CONTENT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "card_fraud_or_skimming",
        re.compile(
            r"\b(?:clone\s+a\s+card|cloned\s+credit\s+card|clonar\s+cartão|clonar\s+cartao|"
            r"card\s+skimmer|bypass\s+3ds|steal\s+card\s+numbers|gerar\s+cartão\s+válido)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "money_laundering_or_illegal",
        re.compile(
            r"\b(?:money\s+laundering|lavagem\s+de\s+dinheiro|evade\s+central\s+bank\s+aml)\b",
            re.IGNORECASE,
        ),
    ),
]

# Matches 15 or 16 contiguous digits (or separated by single spaces/dashes) representing an unmasked PAN
_RAW_PAN_REGEX = re.compile(
    r"(?<![\d\*])(?:\d{4}[\s\-]?){3}\d{3,4}(?![\d\*])"
)

# Matches unmasked CPF (000.000.000-00)
_RAW_CPF_REGEX = re.compile(r"\b(\d{3})\.(\d{3})\.(\d{3})-(\d{2})\b")


class InputGuardrailResult(BaseModel):
    """Outcome of ingress prompt-injection and content safety validation."""

    allowed: bool = True
    guardrail_triggered: bool = False
    violation_category: Literal[
        "none", "prompt_injection", "unsafe_or_toxic", "empty_or_invalid"
    ] = "none"
    matched_rule: str = ""
    reason: str = "Input passed safety and prompt-injection checks."
    safe_refusal_message: str = ""


class OutputGuardrailResult(BaseModel):
    """Outcome of egress PCI-DSS PAN and PII redaction."""

    sanitized_text: str
    modified: bool = False
    redactions_applied: list[str] = Field(default_factory=list)


@traceable_step(name="validate_input_guardrail", run_type="chain")
def validate_input_message(message: str) -> InputGuardrailResult:
    """Inspect user input before routing; block prompt injections and unsafe requests."""
    cleaned = (message or "").strip()
    if not cleaned:
        return InputGuardrailResult(
            allowed=False,
            guardrail_triggered=True,
            violation_category="empty_or_invalid",
            matched_rule="empty_message",
            reason="Empty user message.",
            safe_refusal_message="Please provide a valid question or support request so I can assist you.",
        )

    if not settings.enable_input_guardrails:
        return InputGuardrailResult()

    for rule_name, pattern in _PROMPT_INJECTION_PATTERNS:
        if pattern.search(cleaned):
            logger.warning(
                "input_guardrail_blocked_prompt_injection",
                matched_rule=rule_name,
                message_preview=cleaned[:120],
            )
            return InputGuardrailResult(
                allowed=False,
                guardrail_triggered=True,
                violation_category="prompt_injection",
                matched_rule=rule_name,
                reason=f"Blocked prompt injection or system override attempt ({rule_name}).",
                safe_refusal_message=(
                    "I cannot fulfill requests that attempt to override system security instructions "
                    "or access unauthorized internal records. I am Getnet's virtual assistant and can "
                    "help you with Getnet products (POS terminals, Pix, Crediário, Antecipação, Payment Link) "
                    "or your merchant account support."
                ),
            )

    for rule_name, pattern in _UNSAFE_CONTENT_PATTERNS:
        if pattern.search(cleaned):
            logger.warning(
                "input_guardrail_blocked_unsafe_content",
                matched_rule=rule_name,
                message_preview=cleaned[:120],
            )
            return InputGuardrailResult(
                allowed=False,
                guardrail_triggered=True,
                violation_category="unsafe_or_toxic",
                matched_rule=rule_name,
                reason=f"Blocked unsafe or fraudulent activity request ({rule_name}).",
                safe_refusal_message=(
                    "I cannot assist with requests involving unauthorized card manipulation or financial "
                    "compliance circumvention. If you need help with legitimate security, anti-fraud "
                    "protection, or disputed transactions on your Getnet account, please let me know."
                ),
            )

    return InputGuardrailResult()


def _mask_pan_match(match: re.Match[str]) -> str:
    raw = match.group(0)
    digits = re.sub(r"\D", "", raw)
    if len(digits) < 13 or len(digits) > 19:
        return raw
    return f"{digits[:4]} **** **** {digits[-4:]}"


@traceable_step(name="sanitize_output_guardrail", run_type="chain")
def sanitize_output_message(response_text: str) -> OutputGuardrailResult:
    """Redact unmasked 15-16 digit card numbers (PAN) and sensitive CPFs from outgoing responses."""
    if not response_text or not settings.enable_output_guardrails:
        return OutputGuardrailResult(sanitized_text=response_text or "")

    redactions: list[str] = []
    sanitized = response_text

    if _RAW_PAN_REGEX.search(sanitized):
        sanitized = _RAW_PAN_REGEX.sub(_mask_pan_match, sanitized)
        redactions.append("PCI_PAN_MASKED")

    if _RAW_CPF_REGEX.search(sanitized):
        sanitized = _RAW_CPF_REGEX.sub(r"***.***.***-\4", sanitized)
        redactions.append("LGPD_CPF_MASKED")

    modified = len(redactions) > 0
    if modified:
        logger.info("output_guardrail_redacted_pii", redactions=redactions)

    return OutputGuardrailResult(
        sanitized_text=sanitized,
        modified=modified,
        redactions_applied=redactions,
    )
