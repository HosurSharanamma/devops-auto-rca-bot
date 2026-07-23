"""live/retrieval.py -- masks PII, then queries the in-memory vector store."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.pii_masking import mask_pii  # noqa: E402

from live.vector_store import query_similar  # noqa: E402


@dataclass
class RetrievalOutcome:
    query_masked_text: str
    redactions_applied: list[str]
    incidents: list[dict]
    retrieval_failed: bool


def retrieve_similar_incidents(collection, cleaned_log_text: str, top_k: int = 3) -> RetrievalOutcome:
    masking_result = mask_pii(cleaned_log_text)

    try:
        incidents = query_similar(collection, masking_result.masked_text, top_k=top_k)
        retrieval_failed = False
    except Exception:
        incidents = []
        retrieval_failed = True

    return RetrievalOutcome(
        query_masked_text=masking_result.masked_text,
        redactions_applied=masking_result.redactions,
        incidents=incidents,
        retrieval_failed=retrieval_failed,
    )
