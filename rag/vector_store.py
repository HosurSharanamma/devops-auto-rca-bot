"""
vector_store.py

Wraps ChromaDB persistence + collection management for the Auto-RCA Bot.

Collection schema per document:
  id                  -> incident id (e.g. "inc-0001")
  document            -> the (PII-masked) log text
  metadata            -> { root_cause_category, root_cause, fix_recommendation }
  embedding           -> produced via rag.embeddings.embed_texts
"""

from __future__ import annotations

import os
from typing import Any

CHROMA_PERSIST_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "chroma_store")
COLLECTION_NAME = "jenkins_incidents"


def get_client():
    import chromadb

    os.makedirs(CHROMA_PERSIST_DIR, exist_ok=True)
    return chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)


def get_collection():
    client = get_client()
    return client.get_or_create_collection(name=COLLECTION_NAME, metadata={"hnsw:space": "cosine"})


def is_ready() -> bool:
    try:
        collection = get_collection()
        return collection.count() > 0
    except Exception:
        return False


def upsert_incidents(records: list[dict[str, Any]]) -> int:
    """Embed and upsert a list of incident records (see data schema in
    scripts/generate_synthetic_data.py) into the ChromaDB collection.
    """
    from rag.embeddings import embed_texts

    if not records:
        return 0

    collection = get_collection()
    ids = [r["id"] for r in records]
    documents = [r["log_text"] for r in records]
    metadatas = [
        {
            "root_cause_category": r["root_cause_category"],
            "root_cause": r["root_cause"],
            "fix_recommendation": r["fix_recommendation"],
        }
        for r in records
    ]
    embeddings = embed_texts(documents)

    collection.upsert(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)
    return len(records)


def query_similar(query_text: str, top_k: int = 3) -> list[dict[str, Any]]:
    """Return the top_k most similar historical incidents to query_text,
    each with a similarity_score in [0, 1] (1 = identical)."""
    from rag.embeddings import embed_text

    collection = get_collection()
    query_embedding = embed_text(query_text)

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )

    matches = []
    ids = results.get("ids", [[]])[0]
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    dists = results.get("distances", [[]])[0]

    for i in range(len(ids)):
        # cosine distance -> similarity (distance in [0, 2] for cosine space)
        similarity = max(0.0, 1.0 - (dists[i] / 2.0))
        matches.append(
            {
                "id": ids[i],
                "log_text": docs[i],
                "root_cause_category": metas[i]["root_cause_category"],
                "root_cause": metas[i]["root_cause"],
                "fix_recommendation": metas[i]["fix_recommendation"],
                "similarity_score": round(similarity, 4),
            }
        )
    return matches
