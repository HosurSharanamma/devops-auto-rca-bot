"""
Use models/schemas.py to define the request and response schemas for the API endpoints.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class RCARequest(BaseModel):
    log_text: str = Field(..., description="Raw Jenkins console log or failure snippet.")
    top_k: int = Field(3, ge=1, le=10, description="Number of similar historical incidents to retrieve.")
    job_name: Optional[str] = Field(None, description="Optional Jenkins job name for traceability.")
    build_number: Optional[int] = Field(None, description="Optional Jenkins build number for traceability.")


class RetrievedIncident(BaseModel):
    id: str
    log_text: str
    root_cause_category: str
    similarity_score: float


class RCAResponse(BaseModel):
    root_cause: str
    fix_recommendation: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    low_confidence_flag: bool
    retrieved_incidents: list[RetrievedIncident]
    redactions_applied: list[str]
    used_fallback: bool
    latency_ms: float
    error: Optional[str] = None


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    vector_store_ready: bool
    llm_reachable: bool
