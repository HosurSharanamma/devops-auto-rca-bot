"""
tests/test_day8_probes.py

Day 8: /livez, /readyz and the warm-up, through the real FastAPI app.
The vector store and model are stubbed: needs pytest + fastapi + httpx +
prometheus-client + requests + tenacity, no torch / ChromaDB / LLM.
"""

import os
os.environ["WARMUP_ON_STARTUP"] = "false"  # tests drive the warm-up themselves

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import api.main as main  # noqa: E402
from api.warmup import FAILED, READY, WARMING, Warmup  # noqa: E402

pytestmark = pytest.mark.api


def client_with(warmup):
    main.warmup = warmup
    return TestClient(main.app)


def test_livez_is_200_even_while_warming():
    c = client_with(Warmup())
    assert c.get("/livez").status_code == 200


def test_readyz_503_while_warming():
    c = client_with(Warmup())
    r = c.get("/readyz")
    assert r.status_code == 503
    assert r.json()["status"] == WARMING


def test_readyz_200_after_successful_warmup():
    w = Warmup()
    w.run([("vector_store", lambda: True), ("embedding_model", lambda: object()),
           ("retrieval", lambda: [])])
    r = client_with(w).get("/readyz")
    assert r.status_code == 200
    assert r.json()["status"] == READY


def test_empty_vector_store_keeps_pod_unready():
    w = Warmup()
    w.run([("vector_store", lambda: False), ("retrieval", lambda: [])])
    r = client_with(w).get("/readyz")
    assert r.status_code == 503
    assert r.json()["status"] == FAILED
    assert "vector_store" in r.json()["detail"]


def test_exception_in_warmup_keeps_pod_unready_and_stops():
    ran = []

    def boom():
        raise RuntimeError("model file missing")

    w = Warmup()
    w.run([("embedding_model", boom), ("retrieval", lambda: ran.append(1))])
    assert w.state == FAILED
    assert "model file missing" in w.detail
    assert ran == []  # later steps not run after a failure


def test_probes_never_call_the_llm(monkeypatch):
    def fail(*a, **k):
        raise AssertionError("probe called the LLM")

    monkeypatch.setattr(main, "check_llm_reachable", fail)
    w = Warmup()
    w.run([])
    c = client_with(w)
    assert c.get("/livez").status_code == 200
    assert c.get("/readyz").status_code == 200


@pytest.mark.metrics
def test_tokens_metric_counts_prompt_and_completion():
    from prometheus_client import REGISTRY
    from api.metrics import record_llm_tokens

    def v(kind):
        return REGISTRY.get_sample_value("rca_llm_tokens_total", {"kind": kind}) or 0.0

    before_p, before_c = v("prompt"), v("completion")
    record_llm_tokens(100, 40)
    assert v("prompt") == before_p + 100
    assert v("completion") == before_c + 40
