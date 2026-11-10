"""
tests/test_pii_to_llm.py

Proves the log text sent to the external LLM is masked. Before the 9 Nov fix
only the vector-store query was masked; the raw log went to Groq.
"""

import pytest

from conftest import ok

pytestmark = [pytest.mark.pii, pytest.mark.llm]

SECRETS = {
    "email": "dev.user@example.com",
    "ip": "10.1.2.3",
    "password": "hunter2",
    "bearer": "abc.def.ghi",
}


@pytest.mark.parametrize("kind", SECRETS.keys())
def test_secret_never_reaches_the_llm(fake_llm, rca, kind):
    fake_llm["responses"] = [ok()]
    log = (f"ERROR: auth failed for {SECRETS['email']} from {SECRETS['ip']} "
           f"password={SECRETS['password']} Authorization: Bearer {SECRETS['bearer']}")
    rca(log)
    assert SECRETS[kind] not in str(fake_llm["bodies"][0]), f"{kind} leaked to the LLM"


def test_placeholders_are_sent_instead(fake_llm, rca):
    fake_llm["responses"] = [ok()]
    rca("contact dev.user@example.com")
    assert "<EMAIL_REDACTED>" in str(fake_llm["bodies"][0])
