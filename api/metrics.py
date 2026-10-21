"""
api/metrics.py

Day 6: Prometheus metrics for the /rca endpoint.

Kept in its own module (no FastAPI, model, ChromaDB or LLM imports) so the
CI test job can unit-test it with only `pytest` + `prometheus-client`
installed -- same reasoning as the Day 5 guardrail tests.

What we measure, and why these and nothing else:
  rca_request_duration_seconds  (histogram, label: outcome)
      End-to-end time of one /rca call: retrieval + LLM call + parsing.
      This is the number a user actually feels. A histogram (not a plain
      average) so we can ask for p95, which is what hides slow outliers.
  rca_requests_total            (counter, labels: outcome, low_confidence)
      Every /rca call, split by how it ended. Gives:
        - error rate        = outcome="llm_error" / all
        - low-confidence rate = low_confidence="true" / outcome="success"

outcome values:
  success      -> LLM answered and the JSON parsed
  llm_error    -> LLM call failed or returned garbage; the API still sent
                  HTTP 200 with a fallback answer, which is exactly why we
                  need a metric -- the status code alone hides this failure
  invalid_input -> request rejected by input validation (HTTP 400)
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

# Buckets chosen for an LLM call over the internet: most answers land in
# 1-10s; anything past 30s is a problem worth seeing separately.
LATENCY_BUCKETS = (0.25, 0.5, 1, 2, 3, 5, 8, 13, 21, 30, 60)

RCA_LATENCY = Histogram(
    "rca_request_duration_seconds",
    "End-to-end latency of POST /rca (retrieval + LLM generation).",
    labelnames=("outcome",),
    buckets=LATENCY_BUCKETS,
)

RCA_REQUESTS = Counter(
    "rca_requests_total",
    "Number of POST /rca requests, by outcome and low-confidence flag.",
    labelnames=("outcome", "low_confidence"),
)


def record_rca(outcome: str, duration_seconds: float, low_confidence: bool) -> None:
    """Record one /rca request. Called once per request from api/main.py."""
    RCA_LATENCY.labels(outcome=outcome).observe(duration_seconds)
    RCA_REQUESTS.labels(outcome=outcome, low_confidence=str(low_confidence).lower()).inc()
