"""
live/rca_generation.py

Same grounded-RCA generation approach as rag/rca_generation.py, but targets
Groq's free, hosted, OpenAI-compatible API instead of a local LM Studio
server -- because a public tool can't assume every visitor has a local
Mistral instance running.

Get a free API key at https://console.groq.com/keys and set it as
GROQ_API_KEY (env var locally, or Streamlit secret when deployed).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
REQUEST_TIMEOUT_SECONDS = float(os.environ.get("LLM_TIMEOUT_SECONDS", "30"))
LOW_CONFIDENCE_THRESHOLD = 0.45

SYSTEM_PROMPT = """You are an expert DevOps Root Cause Analysis assistant for Jenkins CI/CD pipelines.
You are given a NEW failure log and, when available, SIMILAR PAST INCIDENTS retrieved from a
knowledge base of previously resolved incidents. Ground your answer in the similar incidents when
they are relevant; do not invent facts that are not supported by the log or the retrieved context.

Respond with ONLY a JSON object, no markdown, no commentary, in exactly this shape:
{
  "root_cause": "<one or two sentence explanation of the most likely root cause>",
  "fix_recommendation": "<concrete, actionable remediation steps>",
  "confidence": <float between 0 and 1, your confidence that this root cause is correct>
}

If the log does not contain enough information to determine a root cause, set confidence below 0.4
and say so honestly in root_cause rather than guessing."""


@dataclass
class RCAGenerationResult:
    root_cause: str
    fix_recommendation: str
    confidence: float
    low_confidence_flag: bool
    used_fallback: bool
    latency_ms: float
    error: str | None = field(default=None)


class LLMCallError(Exception):
    pass


class MissingAPIKeyError(Exception):
    pass


def _get_api_key() -> str:
    key = os.environ.get("GROQ_API_KEY", "")
    if not key:
        raise MissingAPIKeyError(
            "GROQ_API_KEY is not set. Get a free key at https://console.groq.com/keys "
            "and set it as an environment variable or Streamlit secret."
        )
    return key


def is_llm_configured() -> bool:
    return bool(os.environ.get("GROQ_API_KEY"))


def _build_prompt(cleaned_log_text: str, incidents: list[dict]) -> str:
    if incidents:
        context_lines = []
        for inc in incidents:
            context_lines.append(
                f"- [{inc['root_cause_category']}] similarity={inc['similarity_score']:.2f}\n"
                f"  past_log: {inc['log_text']}\n"
                f"  past_root_cause: {inc['root_cause']}\n"
                f"  past_fix: {inc['fix_recommendation']}"
            )
        context_block = "\n".join(context_lines)
    else:
        context_block = "(no similar past incidents were retrieved -- reason from the log alone)"

    return (
        f"SIMILAR PAST INCIDENTS:\n{context_block}\n\n"
        f"NEW FAILURE LOG:\n{cleaned_log_text}\n\n"
        f"Return the JSON object now."
    )


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((requests.exceptions.RequestException, LLMCallError)),
)
def _call_llm(prompt: str) -> str:
    api_key = _get_api_key()
    response = requests.post(
        f"{GROQ_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": GROQ_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 300,
            "response_format": {"type": "json_object"},
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code == 429:
        raise LLMCallError("Rate limited by Groq's free tier -- please try again in a moment.")
    if response.status_code != 200:
        raise LLMCallError(f"LLM endpoint returned status {response.status_code}: {response.text[:200]}")

    data = response.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise LLMCallError(f"Unexpected LLM response shape: {data}") from exc


def _parse_llm_json(raw_content: str) -> dict:
    text = raw_content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def generate_rca(cleaned_log_text: str, incidents: list[dict], retrieval_failed: bool) -> RCAGenerationResult:
    start = time.perf_counter()
    prompt = _build_prompt(cleaned_log_text, incidents)

    try:
        raw_content = _call_llm(prompt)
        parsed = _parse_llm_json(raw_content)

        root_cause = str(parsed.get("root_cause", "")).strip()
        fix_recommendation = str(parsed.get("fix_recommendation", "")).strip()
        confidence = float(parsed.get("confidence", 0.0))
        confidence = min(max(confidence, 0.0), 1.0)

        if not root_cause or not fix_recommendation:
            raise LLMCallError("LLM response missing required fields root_cause/fix_recommendation")

        low_confidence_flag = confidence < LOW_CONFIDENCE_THRESHOLD
        latency_ms = (time.perf_counter() - start) * 1000

        return RCAGenerationResult(
            root_cause=root_cause,
            fix_recommendation=fix_recommendation,
            confidence=confidence,
            low_confidence_flag=low_confidence_flag,
            used_fallback=retrieval_failed,
            latency_ms=round(latency_ms, 2),
        )

    except MissingAPIKeyError as exc:
        latency_ms = (time.perf_counter() - start) * 1000
        return RCAGenerationResult(
            root_cause="This deployment is not configured with an LLM API key yet.",
            fix_recommendation="Site operator: set GROQ_API_KEY (see live/README.md).",
            confidence=0.0,
            low_confidence_flag=True,
            used_fallback=True,
            latency_ms=round(latency_ms, 2),
            error=str(exc),
        )
    except (requests.exceptions.RequestException, LLMCallError, json.JSONDecodeError, ValueError) as exc:
        latency_ms = (time.perf_counter() - start) * 1000
        return RCAGenerationResult(
            root_cause="Unable to determine root cause automatically.",
            fix_recommendation="Please retry, or escalate to an on-call engineer with the raw log attached.",
            confidence=0.0,
            low_confidence_flag=True,
            used_fallback=True,
            latency_ms=round(latency_ms, 2),
            error=f"llm_call_failed: {exc}",
        )
