"""Mask credentials, payment data and government IDs before any text is sent to the model or stored
(PRD context exclusions + guardrail 'personal data processed')."""
from __future__ import annotations

import re

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("PASSWORD", re.compile(r"(?i)\b(password|passcode|pwd|pin|otp)\b(\s*(?:is|:|=|-)\s*)\S+")),
    ("API_KEY", re.compile(r"\b(?:sk|pk|rk|gsk|api|key|token)[-_][A-Za-z0-9_\-]{16,}\b")),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}\b")),
    ("BANK_ACCOUNT", re.compile(r"(?i)\b(account|a/c|acct)\.?\s*(?:no\.?|number|#)?\s*[:\-]?\s*\d{6,18}\b")),
    ("IFSC", re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")),
    ("CARD", re.compile(r"\b(?:\d[ -]?){12,18}\d\b")),
    ("AADHAAR", re.compile(r"\b\d{4}\s\d{4}\s\d{4}\b")),
    ("PAN", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
]


def mask_sensitive(text: str) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}
    for label, pattern in _PATTERNS:

        def _sub(m: re.Match[str], label: str = label) -> str:
            counts[label] = counts.get(label, 0) + 1
            if label == "PASSWORD":
                return f"{m.group(1)}{m.group(2)}[MASKED_{label}]"
            if label == "BANK_ACCOUNT":
                return f"{m.group(1)} [MASKED_{label}]"
            return f"[MASKED_{label}]"

        text = pattern.sub(_sub, text)
    return text, counts
