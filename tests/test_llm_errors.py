"""
tests/test_llm_errors.py

Day 7: proves how rag/rca_generation.py behaves when the LLM provider
misbehaves. requests.post is replaced with a fake, so no network, no Groq
quota, no model. Needs only pytest + requests + tenacity.
"""

import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402
from tenacity import wait_none  # noqa: E402

import rag.rca_generation as gen  # noqa: E402


class FakeResponse:
    def __init__(self, status_code, body=None, text="", headers=None):
        self.status_code = status_code
        self._body = body
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._body


def _ok(content):
    return FakeResponse(200, {"choices": [{"message": {"content": content}}]})


@pytest.fixture
def calls(monkeypatch):
    """Replaces requests.post with a queue of fake responses and counts calls.
    Also removes the 1-8s retry wait so the tests run instantly."""
    state = {"count": 0, "responses": []}

    def fake_post(*args, **kwargs):
        state["count"] += 1
        return state["responses"].pop(0)

    monkeypatch.setattr(gen.requests, "post", fake_post)
    monkeypatch.setattr(gen._call_llm.retry, "wait", wait_none())
    return state


def test_429_is_rate_limited_and_not_retried(calls, caplog):
    calls["responses"] = [FakeResponse(429, text="Rate limit reached (OTPM)", headers={"retry-after": "42"})]

    with caplog.at_level(logging.WARNING, logger="rca.generation"):
        result = gen.generate_rca("ERROR: build failed", incidents=[], retrieval_failed=False)

    assert calls["count"] == 1  # no retry burst against a per-minute quota
    assert result.error_type == "rate_limited"
    assert "retry after 42s" in result.error
    assert result.used_fallback is True
    assert "type=rate_limited" in caplog.text  # visible in kubectl logs


def test_500_is_retried_then_llm_error(calls, caplog):
    calls["responses"] = [FakeResponse(500, text="boom")] * 3

    with caplog.at_level(logging.WARNING, logger="rca.generation"):
        result = gen.generate_rca("ERROR: build failed", incidents=[], retrieval_failed=False)

    assert calls["count"] == 3  # transient errors still get 3 attempts
    assert result.error_type == "llm_error"
    assert "type=llm_error" in caplog.text


def test_500_then_success_recovers(calls):
    calls["responses"] = [
        FakeResponse(500, text="boom"),
        _ok('{"root_cause": "OOM", "fix_recommendation": "raise memory", "confidence": 0.9}'),
    ]
    result = gen.generate_rca("Killed (137)", incidents=[], retrieval_failed=False)

    assert calls["count"] == 2
    assert result.error_type is None
    assert result.confidence == 0.9


def test_missing_confidence_is_logged_not_silent(calls, caplog):
    calls["responses"] = [_ok('{"root_cause": "git auth", "fix_recommendation": "add credentials"}')]

    with caplog.at_level(logging.WARNING, logger="rca.generation"):
        result = gen.generate_rca("fatal: could not read Username", incidents=[], retrieval_failed=False)

    assert result.error_type is None
    assert result.confidence == 0.0
    assert result.low_confidence_flag is True
    assert "confidence missing or not a number" in caplog.text


def test_real_zero_confidence_is_not_flagged_as_missing(calls, caplog):
    calls["responses"] = [_ok('{"root_cause": "unclear", "fix_recommendation": "more logs", "confidence": 0}')]

    with caplog.at_level(logging.WARNING, logger="rca.generation"):
        result = gen.generate_rca("build failed", incidents=[], retrieval_failed=False)

    assert result.confidence == 0.0
    assert "confidence missing" not in caplog.text
