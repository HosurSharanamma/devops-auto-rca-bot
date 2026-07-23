
"""
Grounded prompt using Retrieval incidents calls Model through LM Studio API to 
generate RCA and fix recommendation"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

LM_STUDIO_BASE_URL = os.environ.get("LM_STUDIO_BASE_URL", "http://localhost:1234/v1")
LM_STUDIO_MODEL = os.environ.get("LM_STUDIO_MODEL", "mistral-7b-instruct")
REQUEST_TIMEOUT_SECONDS = float(os.environ.get("LLM_TIMEOUT_SECONDS", "400"))
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
    response = requests.post(
        f"{LM_STUDIO_BASE_URL}/chat/completions",
        json={
            "model": LM_STUDIO_MODEL,
            "messages": [
                {"role": "user", "content": f"{SYSTEM_PROMPT}\n\n{prompt}"},
            ],
            "temperature": 0.2,
            "max_tokens": 200,
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
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

    except (requests.exceptions.RequestException, LLMCallError, json.JSONDecodeError, ValueError) as exc:
        # API Failures / malformed output -> structured error, never a raw traceback to the caller.
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
