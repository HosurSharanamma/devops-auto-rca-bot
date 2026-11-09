
"""
Grounded prompt using Retrieval incidents calls Model through LM Studio API to 
generate RCA and fix recommendation"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field

import requests
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from utils.pii_masking import mask_pii

# Day 7: every LLM failure is now written to the pod log (kubectl logs), not
# only returned to the caller. On Day 6 the metric showed THAT calls failed,
# but nothing recorded WHY.
logger = logging.getLogger("rca.generation")

# LM_STUDIO_BASE_URL / LM_STUDIO_MODEL are kept as-is for local dev (LM Studio,
# no auth needed). For cloud deployment, point these at any OpenAI-compatible
# hosted endpoint (e.g. Groq: https://api.groq.com/openai/v1) and set
# LLM_API_KEY -- no other code changes needed.
LM_STUDIO_BASE_URL = os.environ.get("LM_STUDIO_BASE_URL", "http://localhost:1234/v1")
LM_STUDIO_MODEL = os.environ.get("LM_STUDIO_MODEL", "mistral-7b-instruct")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
# Day 8: was 400 s. With 3 attempts a request could hang ~20 min. A user
# waiting for an RCA gives up long before that; 30 s is plenty for Groq.
REQUEST_TIMEOUT_SECONDS = float(os.environ.get("LLM_TIMEOUT_SECONDS", "30"))
# Day 8: was 200. Too small once the answer is wrapped in JSON; a cut-off
# answer loses its last field (that is how "confidence" went missing).
MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "400"))
# Day 8: provider-specific knobs, OFF by default so local LM Studio keeps
# working unchanged. Turned on for Groq in k8s/01-configmap.yaml.
#   LLM_JSON_MODE=true          -> response_format json_object (valid JSON only)
#   LLM_REASONING_EFFORT=none   -> qwen3 is a reasoning model; its hidden
#                                  "thinking" tokens count against the
#                                  output-token quota and max_tokens
#   LLM_REASONING_FORMAT=hidden -> never return thinking text in the answer
LLM_JSON_MODE = os.environ.get("LLM_JSON_MODE", "false").lower() == "true"
LLM_REASONING_EFFORT = os.environ.get("LLM_REASONING_EFFORT", "")
LLM_REASONING_FORMAT = os.environ.get("LLM_REASONING_FORMAT", "")
# Day 8: Groq's Retry-After on 429 is 2-3 s (Day 7 finding). Waiting that
# long ONCE usually succeeds. Anything longer -> fail fast, tell the user.
MAX_RETRY_AFTER_SECONDS = float(os.environ.get("LLM_MAX_RETRY_AFTER_SECONDS", "5"))
LOW_CONFIDENCE_THRESHOLD = 0.45


def _auth_headers() -> dict:
    """Bearer header when LLM_API_KEY is set (hosted APIs like Groq); empty
    dict for local LM Studio, which needs no auth."""
    return {"Authorization": f"Bearer {LLM_API_KEY}"} if LLM_API_KEY else {}


def check_llm_reachable() -> bool:
    """Used by api/main.py's /health endpoint. Single source of truth for
    how we talk to the LLM backend, so the health check and the real call
    never drift apart."""
    try:
        resp = requests.get(f"{LM_STUDIO_BASE_URL}/models", headers=_auth_headers(), timeout=3)
        return resp.status_code == 200
    except requests.exceptions.RequestException:
        return False

SYSTEM_PROMPT = """You are an expert DevOps Root Cause Analysis assistant for Jenkins CI/CD pipelines.
You are given a NEW failure log and, when available, SIMILAR PAST INCIDENTS retrieved from a
knowledge base of previously resolved incidents. Ground your answer in the similar incidents when
they are relevant; do not invent facts that are not supported by the log or the retrieved context.

Respond with ONLY a JSON object, no markdown, no commentary, in exactly this shape
(keep "confidence" FIRST):
{
  "confidence": <float between 0 and 1, your confidence that this root cause is correct>,
  "root_cause": "<at most two short sentences>",
  "fix_recommendation": "<at most three short, concrete steps>"
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
    # Day 7: None = success, "rate_limited" = provider quota (HTTP 429),
    # "llm_error" = anything else. Lets metrics separate "Groq said slow
    # down" from "something is broken".
    error_type: str | None = field(default=None)
    # Day 8: token usage reported by the provider, for the quota metric.
    prompt_tokens: int = 0
    completion_tokens: int = 0


class LLMCallError(Exception):
    pass


class RateLimitedError(LLMCallError):
    """HTTP 429 from the LLM provider. Never retried by the generic retry
    loop (1-8 s blind backoff). Instead generate_rca() waits for the
    provider's own Retry-After ONCE, if it is short (Day 8)."""

    def __init__(self, message: str, retry_after: float | None):
        super().__init__(message)
        self.retry_after = retry_after


class ClientError(LLMCallError):
    """HTTP 4xx other than 429: bad key (401), retired model (404), bad
    request (400). Retrying cannot fix any of these (Day 8)."""


class TruncatedAnswerError(LLMCallError):
    """finish_reason == "length": the model hit max_tokens. Retrying the
    same prompt with the same limit gives the same cut-off answer."""

    def __init__(self, message: str, usage: dict | None = None):
        super().__init__(message)
        self.usage = usage or {}


@dataclass
class LLMReply:
    content: str
    finish_reason: str | None
    usage: dict


def _parse_retry_after(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def _should_retry(exc: BaseException) -> bool:
    if isinstance(exc, (RateLimitedError, ClientError, TruncatedAnswerError)):
        return False
    return isinstance(exc, (requests.exceptions.RequestException, LLMCallError))


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
    retry=retry_if_exception(_should_retry),
)
def _call_llm(prompt: str) -> LLMReply:
    body = {
        "model": LM_STUDIO_MODEL,
        "messages": [
            {"role": "user", "content": f"{SYSTEM_PROMPT}\n\n{prompt}"},
        ],
        "temperature": 0.2,
        "max_tokens": MAX_TOKENS,
    }
    if LLM_JSON_MODE:
        body["response_format"] = {"type": "json_object"}
    if LLM_REASONING_EFFORT:
        body["reasoning_effort"] = LLM_REASONING_EFFORT
    if LLM_REASONING_FORMAT:
        body["reasoning_format"] = LLM_REASONING_FORMAT

    response = requests.post(
        f"{LM_STUDIO_BASE_URL}/chat/completions",
        headers=_auth_headers(),
        json=body,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code == 429:
        retry_after = _parse_retry_after(response.headers.get("retry-after"))
        raise RateLimitedError(
            f"LLM provider rate limit (HTTP 429), retry after "
            f"{format(retry_after, 'g') if retry_after is not None else 'unknown'}s: {response.text[:200]}",
            retry_after=retry_after,
        )
    if 400 <= response.status_code < 500:
        raise ClientError(f"LLM endpoint returned status {response.status_code}: {response.text[:200]}")
    if response.status_code != 200:
        raise LLMCallError(f"LLM endpoint returned status {response.status_code}: {response.text[:200]}")

    data = response.json()
    try:
        choice = data["choices"][0]
        content = choice["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMCallError(f"Unexpected LLM response shape: {data}") from exc

    finish_reason = choice.get("finish_reason")
    usage = data.get("usage") or {}
    logger.info(
        "llm reply: finish_reason=%s prompt_tokens=%s completion_tokens=%s",
        finish_reason,
        usage.get("prompt_tokens"),
        usage.get("completion_tokens"),
    )
    if finish_reason == "length":
        raise TruncatedAnswerError(
            f"LLM answer cut off at max_tokens={MAX_TOKENS} (finish_reason=length)", usage=usage
        )
    return LLMReply(content=content or "", finish_reason=finish_reason, usage=usage)


def _call_llm_honouring_retry_after(prompt: str) -> LLMReply:
    """Day 8: on 429, wait for the provider's Retry-After and try ONCE more
    if the wait is short. Long or unknown wait -> fail fast."""
    try:
        return _call_llm(prompt)
    except RateLimitedError as exc:
        if exc.retry_after is None or exc.retry_after > MAX_RETRY_AFTER_SECONDS:
            raise
        logger.info("rate limited, waiting %.1fs (Retry-After) then retrying once", exc.retry_after)
        _sleep(exc.retry_after)
        return _call_llm(prompt)


_sleep = time.sleep  # replaced in tests

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _parse_llm_json(raw_content: str) -> dict:
    # Day 8: reasoning models may put <think>...</think> before the JSON.
    text = _THINK_BLOCK.sub("", raw_content).strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def generate_rca(cleaned_log_text: str, incidents: list[dict], retrieval_failed: bool) -> RCAGenerationResult:
    start = time.perf_counter()
    # PII fix: the log used to go to the external LLM UNMASKED (only the
    # retrieval query was masked). Mask here so every caller is covered.
    # Masking is idempotent, so already-masked text is unchanged.
    prompt = _build_prompt(mask_pii(cleaned_log_text).masked_text, incidents)

    usage: dict = {}
    try:
        reply = _call_llm_honouring_retry_after(prompt)
        usage = reply.usage
        raw_content = reply.content
        try:
            parsed = _parse_llm_json(raw_content)
        except json.JSONDecodeError:
            # Day 8: log the FULL answer (Day 7 cut it at 300 chars and hid
            # the evidence). Capped only to protect the log pipeline.
            logger.warning("llm answer is not valid JSON. raw answer: %.4000s", raw_content)
            raise
        if not isinstance(parsed, dict):
            raise LLMCallError(f"LLM answer is JSON but not an object: {raw_content[:200]}")

        root_cause = str(parsed.get("root_cause", "")).strip()
        fix_recommendation = str(parsed.get("fix_recommendation", "")).strip()

        # Day 7: a missing or non-numeric confidence used to become 0.0
        # silently -- indistinguishable from "the model is sure it doesn't
        # know". Still treated as 0.0 (safe: it gets the low-confidence
        # flag), but now logged with the raw answer so we can see which
        # case it was.
        raw_confidence = parsed.get("confidence")
        try:
            confidence = float(raw_confidence)
        except (TypeError, ValueError):
            logger.warning(
                "confidence missing or not a number (got %r); using 0.0. raw answer: %.4000s",
                raw_confidence,
                raw_content,
            )
            confidence = 0.0
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
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
        )

    except (requests.exceptions.RequestException, LLMCallError, json.JSONDecodeError, ValueError) as exc:
        # API Failures / malformed output -> structured error, never a raw traceback to the caller.
        latency_ms = (time.perf_counter() - start) * 1000
        error_type = "rate_limited" if isinstance(exc, RateLimitedError) else "llm_error"
        logger.warning("llm call failed: type=%s latency_ms=%.0f error=%s", error_type, latency_ms, exc)
        failed_usage = getattr(exc, "usage", None) or usage
        return RCAGenerationResult(
            root_cause="Unable to determine root cause automatically.",
            fix_recommendation="Please retry, or escalate to an on-call engineer with the raw log attached.",
            confidence=0.0,
            low_confidence_flag=True,
            used_fallback=True,
            latency_ms=round(latency_ms, 2),
            error=f"llm_call_failed: {exc}",
            error_type=error_type,
            prompt_tokens=int(failed_usage.get("prompt_tokens") or 0),
            completion_tokens=int(failed_usage.get("completion_tokens") or 0),
        )
