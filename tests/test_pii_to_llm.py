"""
tests/test_pii_to_llm.py

Proves the log text sent to the external LLM is PII-masked.
Before this fix only the vector-store query was masked; the raw log
(emails, IPs, tokens) went to Groq. requests.post is faked: no network.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import rag.rca_generation as gen  # noqa: E402


class FakeResponse:
    status_code = 200
    headers = {}
    text = ""

    def json(self):
        return {"choices": [{"message": {"content":
            '{"confidence": 0.9, "root_cause": "x", "fix_recommendation": "y"}'}}]}


def test_prompt_sent_to_llm_is_masked(monkeypatch):
    sent = {}

    def fake_post(url, *args, **kwargs):
        sent["body"] = str(kwargs.get("json"))
        return FakeResponse()

    monkeypatch.setattr(gen.requests, "post", fake_post)

    log = ("ERROR: auth failed for dev.user@example.com from 10.1.2.3 "
           "password=hunter2 Authorization: Bearer abc.def.ghi")
    gen.generate_rca(log, incidents=[], retrieval_failed=False)

    body = sent["body"]
    for secret in ("dev.user@example.com", "10.1.2.3", "hunter2", "abc.def.ghi"):
        assert secret not in body, f"{secret} leaked to the LLM"
    assert "<EMAIL_REDACTED>" in body
