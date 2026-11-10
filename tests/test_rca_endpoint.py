"""
tests/test_rca_endpoint.py

Day 9: POST /rca end to end through the real FastAPI app: validation ->
cleaning -> PII masking -> retrieval -> LLM -> response + metrics.
Only the two outside dependencies are faked: the vector store search
(rag.retrieval.query_similar) and the LLM provider (fixture fake_llm).
"""

import os

os.environ["WARMUP_ON_STARTUP"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from prometheus_client import REGISTRY  # noqa: E402

import api.main as main  # noqa: E402
import rag.retrieval as retrieval  # noqa: E402
from conftest import FakeResponse, ok, too_many  # noqa: E402

pytestmark = pytest.mark.api

PAST_INCIDENT = {
    "id": "inc-0001",
    "log_text": "java.lang.OutOfMemoryError: Java heap space",
    "root_cause_category": "OOM_KILLED",
    "root_cause": "JVM heap too small",
    "fix_recommendation": "Increase -Xmx",
    "similarity_score": 0.91,
}


@pytest.fixture
def client():
    return TestClient(main.app)


@pytest.fixture
def search(monkeypatch):
    """Fake vector-store search: records the query it got, returns one incident."""
    seen = {"queries": [], "fail": False}

    def fake_query_similar(text, top_k=3):
        seen["queries"].append(text)
        if seen["fail"]:
            raise RuntimeError("chroma down")
        return [PAST_INCIDENT]

    monkeypatch.setattr(retrieval, "query_similar", fake_query_similar)
    return seen


def requests_total(outcome, low):
    v = REGISTRY.get_sample_value("rca_requests_total", {"outcome": outcome, "low_confidence": low})
    return v or 0.0


def test_happy_path_returns_rca_and_counts_success(client, search, fake_llm):
    fake_llm["responses"] = [ok()]
    before = requests_total("success", "false")

    r = client.post("/rca", json={"log_text": "ERROR: Killed (137) during mvn test"})

    assert r.status_code == 200
    body = r.json()
    assert body["root_cause"] == "OOM"
    assert body["confidence"] == pytest.approx(0.9)
    assert body["retrieved_incidents"][0]["id"] == "inc-0001"
    assert body["error"] is None
    assert requests_total("success", "false") == before + 1


@pytest.mark.pii
def test_pii_is_masked_on_both_paths(client, search, fake_llm):
    fake_llm["responses"] = [ok()]
    r = client.post("/rca", json={"log_text": "auth failed for dev.user@example.com from 10.1.2.3 password=hunter2"})

    assert set(r.json()["redactions_applied"]) >= {"EMAIL", "IPV4", "GENERIC_SECRET_KV"}
    for secret in ("dev.user@example.com", "10.1.2.3", "hunter2"):
        assert secret not in search["queries"][0]          # vector store path
        assert secret not in str(fake_llm["bodies"][0])   # external LLM path


@pytest.mark.parametrize("payload", [{}, {"log_text": ""}, {"log_text": "   "}, {"log_text": "ab"}],
                         ids=["missing", "empty", "blank", "too-short"])
def test_invalid_input_is_400_and_never_calls_llm(client, search, fake_llm, payload):
    before = requests_total("invalid_input", "false")
    r = client.post("/rca", json=payload)

    assert r.status_code == 400
    assert r.json()["error"] == "invalid_input"
    assert fake_llm["count"] == 0
    assert search["queries"] == []
    assert requests_total("invalid_input", "false") == before + 1


def test_llm_failure_is_200_with_fallback_but_counted_as_error(client, search, fake_llm):
    # The case that motivated the metrics on Day 6: HTTP status looks fine.
    fake_llm["responses"] = [FakeResponse(500, text="boom")] * 3
    before = requests_total("llm_error", "true")

    r = client.post("/rca", json={"log_text": "ERROR: Killed (137) during mvn test"})

    assert r.status_code == 200
    assert r.json()["used_fallback"] is True
    assert requests_total("llm_error", "true") == before + 1


def test_rate_limit_is_counted_separately(client, search, fake_llm):
    fake_llm["responses"] = [too_many("60")]
    before = requests_total("rate_limited", "true")
    client.post("/rca", json={"log_text": "ERROR: Killed (137) during mvn test"})
    assert requests_total("rate_limited", "true") == before + 1


def test_vector_store_down_falls_back_to_llm_only(client, search, fake_llm):
    search["fail"] = True
    fake_llm["responses"] = [ok()]

    r = client.post("/rca", json={"log_text": "ERROR: Killed (137) during mvn test"})

    body = r.json()
    assert r.status_code == 200
    assert body["retrieved_incidents"] == []
    assert body["used_fallback"] is True
    assert "no similar past incidents" in str(fake_llm["bodies"][0])
