"""
tests/test_guardrails.py

Lightweight unit tests for the safety/guardrailing components that don't
require the embedding model, ChromaDB, or a running LLM -- so they run fast
and offline as part of a demo or CI gate.

Run:
    python -m pytest tests/test_guardrails.py -v
    (or, without pytest installed:)
    python tests/test_guardrails.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.log_cleaning import LogValidationError, clean_log_text, validate_log_input  # noqa: E402
from utils.pii_masking import mask_pii  # noqa: E402


def test_mask_pii_email():
    result = mask_pii("Contact admin@acme.com for details.")
    assert "admin@acme.com" not in result.masked_text
    assert "EMAIL" in result.redactions


def test_mask_pii_no_pii():
    result = mask_pii("Build failed with exit code 137.")
    assert result.masked_text == "Build failed with exit code 137."
    assert result.redactions == []


def test_mask_pii_secret_kv():
    result = mask_pii("token=supersecret123 and password: hunter2")
    assert "supersecret123" not in result.masked_text
    assert "hunter2" not in result.masked_text


def test_clean_log_strips_ansi_and_timestamps():
    raw = "\x1b[31m[2026-06-01 10:22:31] ERROR Build failed\x1b[0m"
    cleaned = clean_log_text(raw)
    assert "\x1b" not in cleaned
    assert "2026-06-01" not in cleaned
    assert "ERROR Build failed" in cleaned


def test_validate_log_input_rejects_empty():
    try:
        validate_log_input("   ")
        assert False, "expected LogValidationError"
    except LogValidationError:
        pass


def test_validate_log_input_rejects_none():
    try:
        validate_log_input(None)
        assert False, "expected LogValidationError"
    except LogValidationError:
        pass


def test_validate_log_input_accepts_valid_log():
    cleaned = validate_log_input("Build step 'mvn test' failed. Exit code 137.")
    assert "mvn test" in cleaned


def _run_all():
    tests = [obj for name, obj in list(globals().items()) if name.startswith("test_")]
    passed, failed = 0, 0
    for test in tests:
        try:
            test()
            print(f"PASS: {test.__name__}")
            passed += 1
        except AssertionError as exc:
            print(f"FAIL: {test.__name__} -> {exc}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")


if __name__ == "__main__":
    _run_all()
