""" To find similiar incidents 
"""

from __future__ import annotations

from dataclasses import dataclass

from rag.vector_store import query_similar
from utils.pii_masking import mask_pii


@dataclass
class RetrievalOutcome:
    query_masked_text: str
    redactions_applied: list[str]
    incidents: list[dict]
    retrieval_failed: bool


def retrieve_similar_incidents(cleaned_log_text: str, top_k: int = 3) -> RetrievalOutcome:
    masking_result = mask_pii(cleaned_log_text)

    try:
        incidents = query_similar(masking_result.masked_text, top_k=top_k)
        retrieval_failed = False
    except Exception:
        # "retrieval failure -> fallback to llm only reasoning"
        incidents = []
        retrieval_failed = True

    return RetrievalOutcome(
        query_masked_text=masking_result.masked_text,
        redactions_applied=masking_result.redactions,
        incidents=incidents,
        retrieval_failed=retrieval_failed,
    )
