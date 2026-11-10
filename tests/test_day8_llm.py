"""
tests/test_day8_llm.py

Day 8: LLM call stability. Provider faked via `fake_llm` (conftest.py).
"""

import logging

import pytest

import rag.rca_generation as gen
from conftest import FakeResponse, ok, too_many

pytestmark = pytest.mark.llm


# --- 429 handling --------------------------------------------------------

def test_short_retry_after_waits_and_retries_once(fake_llm, rca):
    fake_llm["responses"] = [too_many("2"), ok()]
    result = rca()
    assert fake_llm["count"] == 2
    assert fake_llm["slept"] == [2.0]
    assert result.error_type is None


def test_second_429_after_waiting_fails_fast(fake_llm, rca):
    fake_llm["responses"] = [too_many("2"), too_many("2")]
    result = rca()
    assert fake_llm["count"] == 2  # exactly one extra try, never a loop
    assert result.error_type == "rate_limited"


@pytest.mark.parametrize("retry_after", ["42", "5.5", None, "not-a-number"],
                         ids=["long", "just-over-limit", "missing", "garbage"])
def test_429_without_short_retry_after_fails_fast(fake_llm, rca, retry_after):
    fake_llm["responses"] = [too_many(retry_after)]
    result = rca()
    assert fake_llm["count"] == 1
    assert fake_llm["slept"] == []
    assert result.error_type == "rate_limited"


# --- errors retrying cannot fix -----------------------------------------

@pytest.mark.parametrize("status", [400, 401, 404])
def test_4xx_is_not_retried(fake_llm, rca, status):
    fake_llm["responses"] = [FakeResponse(status, text="model_not_found")] * 3
    result = rca()
    assert fake_llm["count"] == 1
    assert result.error_type == "llm_error"
    assert str(status) in result.error


def test_truncated_answer_is_not_retried_and_tokens_still_counted(fake_llm, rca):
    fake_llm["responses"] = [ok('{"confidence": 0.9, "root_cause": "OO', finish_reason="length",
                                usage={"prompt_tokens": 100, "completion_tokens": 400})] * 3
    result = rca()
    assert fake_llm["count"] == 1
    assert result.error_type == "llm_error"
    assert "finish_reason=length" in result.error
    assert result.completion_tokens == 400  # quota was spent even though it failed


@pytest.mark.parametrize("status", [500, 502, 503])
def test_5xx_still_retried(fake_llm, rca, status):
    fake_llm["responses"] = [FakeResponse(status, text="busy"), ok()]
    result = rca()
    assert fake_llm["count"] == 2
    assert result.error_type is None


# --- answer parsing -------------------------------------------------------

@pytest.mark.parametrize("raw", [
    "<think>long reasoning {not json}</think>\n" + '{"confidence": 0.9, "root_cause": "OOM", "fix_recommendation": "x"}',
    "```json\n" + '{"confidence": 0.9, "root_cause": "OOM", "fix_recommendation": "x"}' + "\n```",
], ids=["think-block", "markdown-fence"])
def test_wrapped_json_is_still_parsed(fake_llm, rca, raw):
    fake_llm["responses"] = [ok(raw)]
    result = rca()
    assert result.error_type is None
    assert result.confidence == pytest.approx(0.9)


@pytest.mark.parametrize("raw", ["[1, 2, 3]", "Sure! here you go", '{"confidence": 0.9}', ""],
                         ids=["list", "prose", "missing-fields", "empty"])
def test_unusable_answers_become_llm_error_not_a_crash(fake_llm, rca, raw):
    fake_llm["responses"] = [ok(raw)]
    assert rca().error_type == "llm_error"


@pytest.mark.parametrize("raw_confidence, expected", [(1.7, 1.0), (-0.3, 0.0), ("0.5", 0.5)])
def test_confidence_is_clamped_to_0_1(fake_llm, rca, raw_confidence, expected):
    body = f'{{"confidence": {raw_confidence!r}, "root_cause": "x", "fix_recommendation": "y"}}'.replace("'", '"')
    fake_llm["responses"] = [ok(body)]
    assert rca().confidence == pytest.approx(expected)


def test_bad_json_logs_the_full_raw_answer(fake_llm, rca, caplog):
    raw = "Sure! " + "x" * 1000 + " END-OF-ANSWER"
    fake_llm["responses"] = [ok(raw)]
    with caplog.at_level(logging.WARNING, logger="rca.generation"):
        result = rca()
    assert result.error_type == "llm_error"
    assert "END-OF-ANSWER" in caplog.text  # Day 7 cut at 300 chars and lost this


def test_finish_reason_and_tokens_logged_and_returned(fake_llm, rca, caplog):
    fake_llm["responses"] = [ok(usage={"prompt_tokens": 321, "completion_tokens": 54})]
    with caplog.at_level(logging.INFO, logger="rca.generation"):
        result = rca()
    assert "finish_reason=stop" in caplog.text
    assert "completion_tokens=54" in caplog.text
    assert (result.prompt_tokens, result.completion_tokens) == (321, 54)


# --- request body -----------------------------------------------------------

def test_provider_knobs_off_by_default(fake_llm, rca):
    fake_llm["responses"] = [ok()]
    rca()
    body = fake_llm["bodies"][0]
    for key in ("response_format", "reasoning_effort", "reasoning_format"):
        assert key not in body  # local LM Studio must keep working
    assert body["max_tokens"] == gen.MAX_TOKENS


def test_provider_knobs_sent_when_configured(fake_llm, rca, monkeypatch):
    monkeypatch.setattr(gen, "LLM_JSON_MODE", True)
    monkeypatch.setattr(gen, "LLM_REASONING_EFFORT", "none")
    monkeypatch.setattr(gen, "LLM_REASONING_FORMAT", "hidden")
    fake_llm["responses"] = [ok()]
    rca()
    body = fake_llm["bodies"][0]
    assert body["response_format"] == {"type": "json_object"}
    assert body["reasoning_effort"] == "none"
    assert body["reasoning_format"] == "hidden"


@pytest.mark.unit
def test_prompt_asks_for_confidence_first():
    assert gen.SYSTEM_PROMPT.index('"confidence"') < gen.SYSTEM_PROMPT.index('"root_cause"')


@pytest.mark.unit
def test_default_timeout_is_short():
    assert gen.REQUEST_TIMEOUT_SECONDS <= 60
