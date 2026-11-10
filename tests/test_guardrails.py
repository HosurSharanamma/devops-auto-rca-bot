"""
tests/test_guardrails.py

Unit tests for input validation, log cleaning and PII masking. No model,
ChromaDB or LLM needed - pure functions, run in milliseconds.

Run:  python -m pytest -m "unit or pii" -v
"""

import pytest

from utils.log_cleaning import MAX_LOG_CHARS, LogValidationError, clean_log_text, validate_log_input
from utils.pii_masking import mask_pii

pytestmark = pytest.mark.unit


# --- PII masking: one case per rule ----------------------------------------

@pytest.mark.pii
@pytest.mark.parametrize("rule, text, secret", [
    ("EMAIL", "Contact admin@acme.com for details.", "admin@acme.com"),
    ("IPV4", "connection refused from 10.0.0.42", "10.0.0.42"),
    ("AWS_ACCESS_KEY", "key AKIAABCDEFGHIJKLMNOP leaked", "AKIAABCDEFGHIJKLMNOP"),
    ("GENERIC_SECRET_KV", "token=supersecret123", "supersecret123"),
    ("GENERIC_SECRET_KV", "password: hunter2", "hunter2"),
    ("BEARER_TOKEN", "Authorization: Bearer abc123.def", "abc123.def"),
    ("JWT", "jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2ln here", "eyJhbGciOiJIUzI1NiJ9"),
    ("PRIVATE_KEY_BLOCK", "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----", "MIIEow"),
    ("PHONE", "call +49-89-1234567 now", "1234567"),
], ids=lambda v: v if isinstance(v, str) and v.isupper() else None)
def test_each_rule_masks_its_secret(rule, text, secret):
    result = mask_pii(text)
    assert secret not in result.masked_text
    assert rule in result.redactions


@pytest.mark.pii
def test_clean_text_is_unchanged():
    result = mask_pii("Build failed with exit code 137.")
    assert result.masked_text == "Build failed with exit code 137."
    assert result.redactions == []


@pytest.mark.pii
@pytest.mark.parametrize("text", [
    "user a@b.com from 10.0.0.1 token=abc Authorization: Bearer xyz.1",
    "-----BEGIN PRIVATE KEY-----\nAAA\n-----END PRIVATE KEY----- password=p",
])
def test_masking_twice_changes_nothing(text):
    # generate_rca() masks text that retrieval may already have masked,
    # so masking must be idempotent.
    once = mask_pii(text).masked_text
    assert mask_pii(once).masked_text == once


@pytest.mark.pii
def test_none_input_is_safe():
    assert mask_pii(None).masked_text == ""


# --- log cleaning -----------------------------------------------------------

def test_clean_log_strips_ansi_and_timestamps():
    raw = "\x1b[31m[2026-06-01 10:22:31] ERROR Build failed\x1b[0m"
    cleaned = clean_log_text(raw)
    assert "\x1b" not in cleaned
    assert "2026-06-01" not in cleaned
    assert "ERROR Build failed" in cleaned


def test_very_long_log_is_truncated():
    cleaned = clean_log_text("x" * (MAX_LOG_CHARS + 500))
    assert cleaned.endswith("[truncated]")
    assert len(cleaned) < MAX_LOG_CHARS + 50


# --- input validation ---------------------------------------------------------

@pytest.mark.parametrize("bad, message", [
    (None, "empty"),
    ("   ", "empty"),
    ("ab", "too short"),
    ("\x00\x01\x02\x03\x04\x05\x06\x07\x08 log", "non-printable"),
], ids=["none", "blank", "too-short", "binary"])
def test_invalid_input_is_rejected_with_a_clear_message(bad, message):
    with pytest.raises(LogValidationError, match=message):
        validate_log_input(bad)


def test_valid_log_is_accepted_and_cleaned():
    cleaned = validate_log_input("[2026-06-01 10:22:31] Build step 'mvn test' failed. Exit code 137.")
    assert "mvn test" in cleaned
    assert "2026-06-01" not in cleaned
