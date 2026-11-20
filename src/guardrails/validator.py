"""Input safety/prompt-injection guardrails and Output PCI-DSS PAN & PII redaction."""

from __future__ import annotations

import base64
import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, Field

from src.config.settings import settings
from src.guardrails.redaction import redact_text_with_tags, sanitize_sensitive_data
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

_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\ufeff\u00ad]")
_BASE64_TOKEN_RE = re.compile(r"\b([A-Za-z0-9+/]{16,}={0,2})\b")
_HOMOGLYPH_MAP = str.maketrans(
    {
        "а": "a",
        "е": "e",
        "о": "o",
        "р": "p",
        "с": "c",
        "х": "x",
        "і": "i",
        "А": "A",
        "Е": "E",
        "О": "O",
        "Р": "P",
        "С": "C",
        "Х": "X",
        "І": "I",
    }
)


def _extract_inspection_candidates(text: str) -> list[str]:
    """Return raw, Unicode-normalized, and decoded base64 strings for injection inspection."""
    normalized = unicodedata.normalize("NFKC", text)
    normalized = _ZERO_WIDTH_RE.sub("", normalized).translate(_HOMOGLYPH_MAP)
    candidates = [text]
    if normalized != text:
        candidates.append(normalized)

    for match in _BASE64_TOKEN_RE.findall(normalized):
        padded = match + ("=" * ((4 - len(match) % 4) % 4))
        try:
            decoded_bytes = base64.b64decode(padded, validate=True)
            decoded = decoded_bytes.decode("utf-8", errors="strict").strip()
            if decoded and any(ch.isalpha() for ch in decoded):
                dec_norm = _ZERO_WIDTH_RE.sub("", unicodedata.normalize("NFKC", decoded)).translate(_HOMOGLYPH_MAP)
                candidates.append(dec_norm)
        except Exception:
            continue

    return candidates


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

    candidates = _extract_inspection_candidates(cleaned)
    safe_preview = sanitize_sensitive_data(cleaned[:120])

    for candidate in candidates:
        for rule_name, pattern in _PROMPT_INJECTION_PATTERNS:
            if pattern.search(candidate):
                logger.warning(
                    "input_guardrail_blocked_prompt_injection",
                    matched_rule=rule_name,
                    message_preview=safe_preview,
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
            if pattern.search(candidate):
                logger.warning(
                    "input_guardrail_blocked_unsafe_content",
                    matched_rule=rule_name,
                    message_preview=safe_preview,
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


@traceable_step(name="sanitize_output_guardrail", run_type="chain")
def sanitize_output_message(response_text: str) -> OutputGuardrailResult:
    """Redact unmasked PANs, CVVs, CPFs/CNPJs, and secrets from outgoing responses."""
    if not response_text or not settings.enable_output_guardrails:
        return OutputGuardrailResult(sanitized_text=response_text or "")

    sanitized, redactions = redact_text_with_tags(response_text)
    modified = len(redactions) > 0
    if modified:
        logger.info("output_guardrail_redacted_pii", redactions=redactions)

    return OutputGuardrailResult(
        sanitized_text=sanitized,
        modified=modified,
        redactions_applied=redactions,
    )
