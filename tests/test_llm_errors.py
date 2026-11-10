"""
tests/test_llm_errors.py

Day 7: how rag/rca_generation.py behaves when the LLM provider misbehaves.
The provider is faked (fixture `fake_llm` in conftest.py): no network, no quota.
"""

import logging

import pytest

from conftest import FakeResponse, ok, too_many

pytestmark = pytest.mark.llm


def test_long_429_is_rate_limited_and_not_retried(fake_llm, rca, caplog):
    fake_llm["responses"] = [too_many("42")]

    with caplog.at_level(logging.WARNING, logger="rca.generation"):
        result = rca()

    assert fake_llm["count"] == 1  # no retry burst against the quota
    assert result.error_type == "rate_limited"
    assert "retry after 42s" in result.error
    assert result.used_fallback is True
    assert "type=rate_limited" in caplog.text  # visible in kubectl logs


def test_500_is_retried_then_llm_error(fake_llm, rca, caplog):
    fake_llm["responses"] = [FakeResponse(500, text="boom")] * 3

    with caplog.at_level(logging.WARNING, logger="rca.generation"):
        result = rca()

    assert fake_llm["count"] == 3  # transient errors still get 3 attempts
    assert result.error_type == "llm_error"
    assert "type=llm_error" in caplog.text


def test_500_then_success_recovers(fake_llm, rca):
    fake_llm["responses"] = [FakeResponse(500, text="boom"), ok()]
    result = rca()

    assert fake_llm["count"] == 2
    assert result.error_type is None
    assert result.confidence == pytest.approx(0.9)


def test_missing_confidence_is_logged_not_silent(fake_llm, rca, caplog):
    fake_llm["responses"] = [ok('{"root_cause": "git auth", "fix_recommendation": "add credentials"}')]

    with caplog.at_level(logging.WARNING, logger="rca.generation"):
        result = rca("fatal: could not read Username")

    assert result.error_type is None
    assert result.confidence == 0.0
    assert result.low_confidence_flag is True
    assert "confidence missing or not a number" in caplog.text


def test_real_zero_confidence_is_not_flagged_as_missing(fake_llm, rca, caplog):
    fake_llm["responses"] = [ok('{"confidence": 0, "root_cause": "unclear", "fix_recommendation": "more logs"}')]

    with caplog.at_level(logging.WARNING, logger="rca.generation"):
        result = rca("build failed")

    assert result.confidence == 0.0
    assert "confidence missing" not in caplog.text
