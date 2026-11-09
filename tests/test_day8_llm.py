"""
tests/test_day8_llm.py

Day 8: LLM call stability. requests.post is faked: no network, no quota.
Needs only pytest + requests + tenacity.
"""

import json
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402
from tenacity import wait_none  # noqa: E402

import rag.rca_generation as gen  # noqa: E402

GOOD = '{"confidence": 0.9, "root_cause": "OOM", "fix_recommendation": "raise memory"}'


class FakeResponse:
    def __init__(self, status_code, body=None, text="", headers=None):
        self.status_code = status_code
        self._body = body
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._body


def ok(content, finish_reason="stop", usage=None):
    return FakeResponse(200, {
        "choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
        "usage": usage if usage is not None else {"prompt_tokens": 120, "completion_tokens": 45},
    })


def too_many(retry_after):
    headers = {"retry-after": retry_after} if retry_after is not None else {}
    return FakeResponse(429, text="Rate limit reached", headers=headers)


@pytest.fixture
def llm(monkeypatch):
    state = {"count": 0, "responses": [], "bodies": [], "slept": []}

    def fake_post(url, *args, **kwargs):
        state["count"] += 1
        state["bodies"].append(kwargs.get("json"))
        return state["responses"].pop(0)

    monkeypatch.setattr(gen.requests, "post", fake_post)
    monkeypatch.setattr(gen._call_llm.retry, "wait", wait_none())
    monkeypatch.setattr(gen, "_sleep", lambda s: state["slept"].append(s))
    return state


def run(log="ERROR: Killed (137)"):
    return gen.generate_rca(log, incidents=[], retrieval_failed=False)


# --- 429 handling --------------------------------------------------------

def test_short_retry_after_waits_and_retries_once(llm):
    llm["responses"] = [too_many("2"), ok(GOOD)]
    result = run()
    assert llm["count"] == 2
    assert llm["slept"] == [2.0]
    assert result.error_type is None


def test_second_429_after_waiting_fails_fast(llm):
    llm["responses"] = [too_many("2"), too_many("2")]
    result = run()
    assert llm["count"] == 2  # exactly one extra try, never a loop
    assert result.error_type == "rate_limited"


def test_long_retry_after_fails_fast_without_waiting(llm):
    llm["responses"] = [too_many("42")]
    result = run()
    assert llm["count"] == 1
    assert llm["slept"] == []
    assert result.error_type == "rate_limited"


def test_missing_retry_after_fails_fast(llm):
    llm["responses"] = [too_many(None)]
    result = run()
    assert llm["count"] == 1
    assert result.error_type == "rate_limited"


# --- errors retrying cannot fix -----------------------------------------

@pytest.mark.parametrize("status", [400, 401, 404])
def test_4xx_is_not_retried(llm, status):
    llm["responses"] = [FakeResponse(status, text="model_not_found")] * 3
    result = run()
    assert llm["count"] == 1
    assert result.error_type == "llm_error"
    assert str(status) in result.error


def test_truncated_answer_is_not_retried_and_tokens_still_counted(llm, caplog):
    llm["responses"] = [ok('{"confidence": 0.9, "root_cause": "OO', finish_reason="length",
                           usage={"prompt_tokens": 100, "completion_tokens": 400})] * 3
    with caplog.at_level(logging.WARNING, logger="rca.generation"):
        result = run()
    assert llm["count"] == 1
    assert result.error_type == "llm_error"
    assert "finish_reason=length" in result.error
    assert result.completion_tokens == 400  # quota was spent even though it failed


def test_5xx_still_retried(llm):
    llm["responses"] = [FakeResponse(503, text="busy"), ok(GOOD)]
    result = run()
    assert llm["count"] == 2
    assert result.error_type is None


# --- answer parsing -------------------------------------------------------

def test_think_block_is_stripped(llm):
    llm["responses"] = [ok("<think>long reasoning {not json}</think>\n" + GOOD)]
    result = run()
    assert result.error_type is None
    assert result.confidence == 0.9


def test_bad_json_logs_the_full_raw_answer(llm, caplog):
    raw = "Sure! " + "x" * 1000 + " END-OF-ANSWER"
    llm["responses"] = [ok(raw)]
    with caplog.at_level(logging.WARNING, logger="rca.generation"):
        result = run()
    assert result.error_type == "llm_error"
    assert "END-OF-ANSWER" in caplog.text  # Day 7 cut at 300 chars and lost this


def test_json_list_instead_of_object_is_an_error_not_a_crash(llm):
    llm["responses"] = [ok("[1, 2, 3]")]
    assert run().error_type == "llm_error"


def test_finish_reason_and_tokens_logged_and_returned(llm, caplog):
    llm["responses"] = [ok(GOOD, usage={"prompt_tokens": 321, "completion_tokens": 54})]
    with caplog.at_level(logging.INFO, logger="rca.generation"):
        result = run()
    assert "finish_reason=stop" in caplog.text
    assert "completion_tokens=54" in caplog.text
    assert (result.prompt_tokens, result.completion_tokens) == (321, 54)


# --- request body -----------------------------------------------------------

def test_provider_knobs_off_by_default(llm):
    llm["responses"] = [ok(GOOD)]
    run()
    body = llm["bodies"][0]
    for key in ("response_format", "reasoning_effort", "reasoning_format"):
        assert key not in body  # local LM Studio must keep working
    assert body["max_tokens"] == gen.MAX_TOKENS


def test_provider_knobs_sent_when_configured(llm, monkeypatch):
    monkeypatch.setattr(gen, "LLM_JSON_MODE", True)
    monkeypatch.setattr(gen, "LLM_REASONING_EFFORT", "none")
    monkeypatch.setattr(gen, "LLM_REASONING_FORMAT", "hidden")
    llm["responses"] = [ok(GOOD)]
    run()
    body = llm["bodies"][0]
    assert body["response_format"] == {"type": "json_object"}
    assert body["reasoning_effort"] == "none"
    assert body["reasoning_format"] == "hidden"


def test_prompt_asks_for_confidence_first():
    template = gen.SYSTEM_PROMPT
    assert template.index('"confidence"') < template.index('"root_cause"')


def test_default_timeout_is_short():
    assert gen.REQUEST_TIMEOUT_SECONDS <= 60
