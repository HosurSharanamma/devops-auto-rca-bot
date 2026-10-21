"""
tests/test_metrics.py

Day 6: proves record_rca() actually changes the numbers Prometheus will
scrape. Needs only pytest + prometheus-client (no model, no LLM).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from prometheus_client import REGISTRY, generate_latest  # noqa: E402

from api.metrics import record_rca  # noqa: E402


def _value(name, labels):
    v = REGISTRY.get_sample_value(name, labels)
    return 0.0 if v is None else v


def test_success_is_counted_and_timed():
    before_count = _value("rca_requests_total", {"outcome": "success", "low_confidence": "false"})
    before_obs = _value("rca_request_duration_seconds_count", {"outcome": "success"})

    record_rca("success", 2.5, low_confidence=False)

    assert _value("rca_requests_total", {"outcome": "success", "low_confidence": "false"}) == before_count + 1
    assert _value("rca_request_duration_seconds_count", {"outcome": "success"}) == before_obs + 1


def test_low_confidence_is_a_separate_series():
    before = _value("rca_requests_total", {"outcome": "success", "low_confidence": "true"})
    record_rca("success", 1.0, low_confidence=True)
    assert _value("rca_requests_total", {"outcome": "success", "low_confidence": "true"}) == before + 1


def test_slow_request_lands_in_the_right_bucket():
    # 9s is above the 8s bucket and inside the 13s bucket.
    le8 = _value("rca_request_duration_seconds_bucket", {"outcome": "llm_error", "le": "8.0"})
    le13 = _value("rca_request_duration_seconds_bucket", {"outcome": "llm_error", "le": "13.0"})
    record_rca("llm_error", 9.0, low_confidence=True)
    assert _value("rca_request_duration_seconds_bucket", {"outcome": "llm_error", "le": "8.0"}) == le8
    assert _value("rca_request_duration_seconds_bucket", {"outcome": "llm_error", "le": "13.0"}) == le13 + 1


def test_metrics_text_output_contains_our_metrics():
    record_rca("invalid_input", 0.01, low_confidence=False)
    text = generate_latest(REGISTRY).decode()
    assert "rca_request_duration_seconds_bucket" in text
    assert "rca_requests_total" in text
