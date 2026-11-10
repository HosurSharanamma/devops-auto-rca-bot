"""
tests/conftest.py

Day 9: shared test helpers. pytest loads this file automatically, so every
test file can use these fixtures without importing anything. Before Day 9
the fake HTTP response and the fake-LLM fixture were copied into 3 files.
"""

import pytest
from tenacity import wait_none

import rag.rca_generation as gen

GOOD_ANSWER = '{"confidence": 0.9, "root_cause": "OOM", "fix_recommendation": "raise memory"}'


class FakeResponse:
    """Stands in for requests.Response: status code, headers, body."""

    def __init__(self, status_code, body=None, text="", headers=None):
        self.status_code = status_code
        self._body = body
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._body


def ok(content=GOOD_ANSWER, finish_reason="stop", usage=None):
    """A successful LLM reply (HTTP 200) with the given answer text."""
    return FakeResponse(200, {
        "choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
        "usage": usage if usage is not None else {"prompt_tokens": 120, "completion_tokens": 45},
    })


def too_many(retry_after):
    """HTTP 429 (rate limit), optionally with a Retry-After header."""
    headers = {"retry-after": retry_after} if retry_after is not None else {}
    return FakeResponse(429, text="Rate limit reached", headers=headers)


@pytest.fixture
def fake_llm(monkeypatch):
    """Replaces the real HTTP call to the LLM provider.

    Put FakeResponse objects in fake_llm["responses"]; each call takes the
    next one. Records how many calls were made, the JSON body of each call,
    and every sleep (so retry waits cost no real time).
    """
    state = {"count": 0, "responses": [], "bodies": [], "slept": []}

    def fake_post(url, *args, **kwargs):
        state["count"] += 1
        state["bodies"].append(kwargs.get("json"))
        if not state["responses"]:
            raise AssertionError("LLM was called more times than the test expected")
        return state["responses"].pop(0)

    monkeypatch.setattr(gen.requests, "post", fake_post)
    monkeypatch.setattr(gen._call_llm.retry, "wait", wait_none())
    monkeypatch.setattr(gen, "_sleep", lambda seconds: state["slept"].append(seconds))
    return state


@pytest.fixture
def rca():
    """Run one RCA generation with a given log (default: an OOM-style log)."""

    def _run(log="ERROR: Killed (137)", incidents=None):
        return gen.generate_rca(log, incidents=incidents or [], retrieval_failed=False)

    return _run
