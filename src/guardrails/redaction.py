"""Shared PCI-DSS, LGPD, and secret-token sanitization utilities for guardrails, logs, and traces."""

from __future__ import annotations

import re
from typing import Any

# Matches 13-19 digit PANs (contiguous or separated by single spaces/dashes), excluding already masked digits
_RAW_PAN_REGEX = re.compile(r"(?<![\d\*])(?:\d{4}[\s\-]?){3}\d{1,4}(?![\d\*])")
_CONTIGUOUS_PAN_REGEX = re.compile(r"(?<![\d\*])\d{13,19}(?![\d\*])")

# Matches unmasked CPF (000.000.000-00) or explicit CPF: 12345678901
_RAW_CPF_REGEX = re.compile(r"\b(\d{3})\.(\d{3})\.(\d{3})-(\d{2})\b")
_RAW_CPF_COMPACT_REGEX = re.compile(r"(?i)\b(cpf\s*[:=#]?\s*)(\d{9})(\d{2})\b")

# Matches unmasked CNPJ (00.000.000/0000-00)
_RAW_CNPJ_REGEX = re.compile(r"\b(\d{2})\.(\d{3})\.(\d{3})/(\d{4})-(\d{2})\b")

# Matches CVV / CVC security codes (e.g. "CVV: 123", "cvc=4567")
_RAW_CVV_REGEX = re.compile(r"(?i)\b(cvv2?|cvc2?|security\s+code)(\s*[:=#]?\s*)(\d{3,4})\b")

# Matches Bearer tokens and OpenAI/API secret keys
_BEARER_TOKEN_REGEX = re.compile(r"(?i)\b(Bearer\s+)([A-Za-z0-9\-_\.=]{12,})")
_OPENAI_KEY_REGEX = re.compile(r"\b(sk-[A-Za-z0-9\-_]{12,})\b")


def _mask_pan_match(match: re.Match[str]) -> str:
    raw = match.group(0)
    digits = re.sub(r"\D", "", raw)
    if len(digits) < 13 or len(digits) > 19:
        return raw
    return f"{digits[:4]} **** **** {digits[-4:]}"


def redact_text_with_tags(text: str) -> tuple[str, list[str]]:
    """Sanitize sensitive PCI/LGPD/credential patterns from text and return applied redaction tags."""
    if not text:
        return text, []

    redactions: list[str] = []
    sanitized = text

    if _BEARER_TOKEN_REGEX.search(sanitized):
        sanitized = _BEARER_TOKEN_REGEX.sub(r"\1[REDACTED_TOKEN]", sanitized)
        redactions.append("SECRET_TOKEN_MASKED")

    if _OPENAI_KEY_REGEX.search(sanitized):
        sanitized = _OPENAI_KEY_REGEX.sub("[REDACTED_API_KEY]", sanitized)
        if "SECRET_TOKEN_MASKED" not in redactions:
            redactions.append("SECRET_TOKEN_MASKED")

    if _RAW_PAN_REGEX.search(sanitized):
        updated = _RAW_PAN_REGEX.sub(_mask_pan_match, sanitized)
        if updated != sanitized:
            sanitized = updated
            redactions.append("PCI_PAN_MASKED")

    if _CONTIGUOUS_PAN_REGEX.search(sanitized):
        updated = _CONTIGUOUS_PAN_REGEX.sub(_mask_pan_match, sanitized)
        if updated != sanitized:
            sanitized = updated
            if "PCI_PAN_MASKED" not in redactions:
                redactions.append("PCI_PAN_MASKED")

    if _RAW_CVV_REGEX.search(sanitized):
        sanitized = _RAW_CVV_REGEX.sub(r"\1\2***", sanitized)
        redactions.append("PCI_CVV_MASKED")

    if _RAW_CPF_REGEX.search(sanitized):
        sanitized = _RAW_CPF_REGEX.sub(r"***.***.***-\4", sanitized)
        redactions.append("LGPD_CPF_MASKED")

    if _RAW_CPF_COMPACT_REGEX.search(sanitized):
        sanitized = _RAW_CPF_COMPACT_REGEX.sub(r"\1*********\3", sanitized)
        if "LGPD_CPF_MASKED" not in redactions:
            redactions.append("LGPD_CPF_MASKED")

    if _RAW_CNPJ_REGEX.search(sanitized):
        sanitized = _RAW_CNPJ_REGEX.sub(r"**.***.***/\4-\5", sanitized)
        redactions.append("LGPD_CNPJ_MASKED")

    return sanitized, redactions


def sanitize_sensitive_data(value: Any) -> Any:
    """Recursively mask PCI-DSS, LGPD, and Bearer/API secrets in strings, dicts, and lists."""
    if isinstance(value, str):
        sanitized, _ = redact_text_with_tags(value)
        return sanitized
    if isinstance(value, dict):
        return {k: sanitize_sensitive_data(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_sensitive_data(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_sensitive_data(item) for item in value)
    return value
