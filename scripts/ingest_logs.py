"""
Loads a synthetic dataset of Jenkins CI/CD failure logs into the ChromaDB vector 
store for RAG retrieval.
Usage:
    python scripts/ingest_logs.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rag.vector_store import upsert_incidents  # noqa: E402

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "synthetic_jenkins_logs.json")


def main():
    if not os.path.exists(DATA_PATH):
        print(f"Dataset not found at {DATA_PATH}. Run generate_synthetic_data.py first.")
        sys.exit(1)

    with open(DATA_PATH, "r", encoding="utf-8") as f:
        records = json.load(f)

    count = upsert_incidents(records)
    print(f"Ingested {count} incidents into the ChromaDB collection 'jenkins_incidents'.")


if __name__ == "__main__":
    main()
