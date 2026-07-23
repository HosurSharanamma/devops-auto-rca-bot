"""
live/vector_store.py

Lightweight variant of rag/vector_store.py for the public deployment.

Two differences from the capstone version:
  1. Uses ChromaDB's built-in ONNX MiniLM embedding function instead of
     sentence-transformers + torch. Same underlying model (all-MiniLM-L6-v2),
     but ~50MB instead of ~800MB -- matters on a free hosting tier.
  2. Uses an in-memory (ephemeral) Chroma client rebuilt from the bundled
     dataset on app startup instead of a persistent on-disk store. The
     dataset is small and fixed, so rebuilding takes a couple of seconds
     and avoids any question of disk persistence surviving a free-tier
     container restart.
"""

from __future__ import annotations

import json
import os
from typing import Any

COLLECTION_NAME = "jenkins_incidents"
DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "synthetic_jenkins_logs.json")


def build_collection():
    """Create a fresh in-memory collection and ingest the bundled dataset.

    Intended to be called once per process and cached by the caller
    (see app.py's st.cache_resource usage) -- not on every request.
    """
    import chromadb

    client = chromadb.EphemeralClient()
    collection = client.get_or_create_collection(name=COLLECTION_NAME, metadata={"hnsw:space": "cosine"})

    with open(DATA_PATH, "r", encoding="utf-8") as f:
        records = json.load(f)

    collection.upsert(
        ids=[r["id"] for r in records],
        documents=[r["log_text"] for r in records],
        metadatas=[
            {
                "root_cause_category": r["root_cause_category"],
                "root_cause": r["root_cause"],
                "fix_recommendation": r["fix_recommendation"],
            }
            for r in records
        ],
    )
    return collection


def query_similar(collection, query_text: str, top_k: int = 3) -> list[dict[str, Any]]:
    """Return the top_k most similar historical incidents to query_text."""
    results = collection.query(
        query_texts=[query_text],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )

    matches = []
    ids = results.get("ids", [[]])[0]
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    dists = results.get("distances", [[]])[0]

    for i in range(len(ids)):
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
