"""
Masks emails, tokens,secret key,passwords,IP addreess, phone numbers
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class MaskingResult:
    masked_text: str
    redactions: list[str] = field(default_factory=list)  # which rule names fired



_RULES: dict[str, tuple[re.Pattern, str]] = {
    "EMAIL": (re.compile(r"[\w\.-]+@[\w\.-]+\.\w+"), "<EMAIL_REDACTED>"),
    "IPV4": (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "<IP_REDACTED>"),
    "AWS_ACCESS_KEY": (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "<AWS_KEY_REDACTED>"),
    "GENERIC_SECRET_KV": (
        re.compile(
            r"(?i)\b(api[_-]?key|token|secret|password|passwd|pwd)\s*[=:]\s*[^\s'\"]+"
        ),
        r"\1=<SECRET_REDACTED>",
    ),
    "BEARER_TOKEN": (re.compile(r"(?i)bearer\s+[A-Za-z0-9\-_\.]+"), "Bearer <TOKEN_REDACTED>"),
    "JWT": (re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"), "<JWT_REDACTED>"),
    "PRIVATE_KEY_BLOCK": (
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
        "<PRIVATE_KEY_REDACTED>",
    ),
    "PHONE": (re.compile(r"\b\+?\d{1,3}[-.\s]?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}\b"), "<PHONE_REDACTED>"),
}


def mask_pii(text: str) -> MaskingResult:
    """Apply every masking rule to `text` and return the sanitized text
    plus a list of which rule names actually redacted something.

    Order matters: JWT/private-key/bearer patterns run before the more
    generic secret-KV pattern to avoid double-masking artifacts.
    """
    if text is None:
        return MaskingResult(masked_text="", redactions=[])

    masked = text
    fired: list[str] = []

    ordered_rule_names = [
        "PRIVATE_KEY_BLOCK",
        "JWT",
        "BEARER_TOKEN",
        "AWS_ACCESS_KEY",
        "GENERIC_SECRET_KV",
        "EMAIL",
        "IPV4",
        "PHONE",
    ]

    for name in ordered_rule_names:
        pattern, replacement = _RULES[name]
        new_masked, n_subs = pattern.subn(replacement, masked)
        if n_subs > 0:
            fired.append(name)
            masked = new_masked

    return MaskingResult(masked_text=masked, redactions=fired)


if __name__ == "__main__":
    sample = (
        "User admin@acme.com failed login from 10.0.0.42. "
        "token=abcd1234efgh5678 Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.abc.def "
        "AWS key AKIAABCDEFGHIJKLMNOP leaked. Call them at +49-89-1234567."
    )
    result = mask_pii(sample)
    print("Masked:", result.masked_text)
    print("Rules fired:", result.redactions)
