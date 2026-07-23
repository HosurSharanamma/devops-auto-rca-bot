"""
api/main.py

FastAPI backend for the Auto-RCA Bot.

Endpoints:
  GET  /health  -> liveness + readiness of vector store and LLM
  POST /rca     -> full RAG pipeline: validate -> clean -> mask PII ->
                    retrieve similar incidents -> generate grounded RCA

Run:
    uvicorn api.main:app --reload --port 8000
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from models.schemas import ErrorResponse, HealthResponse, RCAResponse, RetrievedIncident
from rag.rca_generation import LM_STUDIO_BASE_URL, generate_rca
from rag.retrieval import retrieve_similar_incidents
from rag.vector_store import is_ready
from utils.log_cleaning import LogValidationError, validate_log_input

app = FastAPI(
    title="Auto-RCA Bot API",
    description="GenAI-powered Root Cause Analysis for Jenkins CI/CD failures.",
    version="1.0.0",
)


def _check_llm_reachable() -> bool:
    try:
        resp = requests.get(f"{LM_STUDIO_BASE_URL}/models", timeout=3)
        return resp.status_code == 200
    except requests.exceptions.RequestException:
        return False


@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(
        status="ok",
        vector_store_ready=is_ready(),
        llm_reachable=_check_llm_reachable(),
    )


@app.post("/rca", response_model=RCAResponse, responses={400: {"model": ErrorResponse}})
def rca(request: dict):
    """Accepts a raw dict body matching models.schemas.RCARequest.

    A plain dict (rather than the pydantic model directly) is used at the
    signature level so that malformed bodies fall through to our own
    structured error handling instead of FastAPI's default 422 response --
    keeping the "structured error message" behaviour consistent across all
    failure modes described in the capstone's Error Handling Strategy.
    """
    log_text = request.get("log_text")
    top_k = int(request.get("top_k", 3))

    try:
        cleaned = validate_log_input(log_text)
    except LogValidationError as exc:
        return JSONResponse(status_code=400, content=ErrorResponse(error="invalid_input", detail=str(exc)).model_dump())

    retrieval_outcome = retrieve_similar_incidents(cleaned, top_k=top_k)
    generation = generate_rca(
        cleaned_log_text=cleaned,
        incidents=retrieval_outcome.incidents,
        retrieval_failed=retrieval_outcome.retrieval_failed,
    )

    response = RCAResponse(
        root_cause=generation.root_cause,
        fix_recommendation=generation.fix_recommendation,
        confidence=generation.confidence,
        low_confidence_flag=generation.low_confidence_flag,
        retrieved_incidents=[
            RetrievedIncident(
                id=i["id"],
                log_text=i["log_text"],
                root_cause_category=i["root_cause_category"],
                similarity_score=i["similarity_score"],
            )
            for i in retrieval_outcome.incidents
        ],
        redactions_applied=retrieval_outcome.redactions_applied,
        used_fallback=generation.used_fallback,
        latency_ms=generation.latency_ms,
        error=generation.error,
    )
    return response
